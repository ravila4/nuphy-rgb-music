import AppKit
import os

private let logger = Logger(subsystem: "com.nuphy-rgb.menu", category: "AppState")

/// Central state for the menu bar app.
/// Observable so SwiftUI views update automatically.
@MainActor
@Observable
class AppState: DaemonClientDelegate {
    let client = DaemonClient()
    let manager = DaemonManager()

    // Cached state from daemon
    var effects: [String] = []
    var effectDescriptions: [String: String] = [:]
    var sidelights: [String] = []
    var activeEffect: String?
    var activeSidelight: String?
    var isConnected = false
    var audioLevel: Double = 0.0
    var isPaused = false

    // Tuning window state
    var selectedEffectForTuning: String?
    var paramsByEffect: [String: [ParamSchema]] = [:]

    /// Trailing debounce tasks per effect for disk writes.
    private var pendingWrites: [String: Task<Void, Never>] = [:]
    private let writeDebounceMillis: UInt64 = 300

    var statusIcon: String {
        if isPaused { return "pause.circle" }
        return isConnected ? "waveform" : "waveform.slash"
    }

    init() {
        client.delegate = self
        logger.warning("init called")
        connectOrStart()
    }

    // MARK: - Connection

    func connectOrStart() {
        let running = manager.detectRunning()
        logger.warning("connectOrStart: detectRunning=\(running)")
        if running {
            logger.warning("connecting to existing daemon")
            client.connect()
        } else {
            logger.warning("starting daemon")
            startDaemon()
        }
    }

    func startDaemon() {
        guard manager.state == .stopped else { return }
        do {
            try manager.start()
            let socketPath = manager.effectiveSocketPath
            logger.warning("daemon started, waiting for socket at \(socketPath)")
            Task {
                for i in 0..<20 {  // up to 5 seconds
                    try await Task.sleep(for: .milliseconds(250))
                    let path = self.manager.effectiveSocketPath
                    let ready = DaemonClient.probe(socketPath: path)
                    logger.warning("poll \(i): probe=\(ready) path=\(path)")
                    if ready {
                        logger.warning("socket ready, connecting")
                        self.client.connect(socketPath: path)
                        return
                    }
                }
                logger.warning("timed out waiting for daemon socket")
            }
        } catch {
            logger.error("failed to start daemon: \(error)")
        }
    }

    func stopDaemon() {
        Task {
            await manager.stop(via: client)
        }
    }

    func quitApp() async {
        await manager.stop(via: client)
        NSApplication.shared.terminate(nil)
    }

    // MARK: - Effect switching

    func togglePause() {
        Task {
            do {
                let result = try await client.setPaused(!isPaused)
                isPaused = result.paused
            } catch {
                logger.error("setPaused error: \(error)")
            }
        }
    }

    func selectEffect(_ name: String) {
        Task {
            do {
                let result = try await client.setEffect(name: name)
                activeEffect = result.name
            } catch {
                logger.error("setEffect error: \(error)")
            }
        }
    }

    func selectSidelight(_ name: String) {
        Task {
            do {
                let result = try await client.setSidelight(name: name)
                activeSidelight = result.name
            } catch {
                logger.error("setSidelight error: \(error)")
            }
        }
    }

    // MARK: - Param tuning

    /// Prepare the tuning window for display: default the selection to
    /// whatever is currently playing, and load its params if not cached.
    func openTuningWindow() {
        if selectedEffectForTuning == nil {
            selectedEffectForTuning = activeEffect ?? effects.first
        }
        if let sel = selectedEffectForTuning, paramsByEffect[sel] == nil {
            loadParams(for: sel)
        }
    }

    /// Load params for a given effect into the cache. Safe to call
    /// repeatedly; always replaces the cached array wholesale.
    func loadParams(for effect: String) {
        Task {
            do {
                let params = try await client.getParamsFor(effect: effect)
                paramsByEffect[effect] = params
            } catch {
                logger.error("loadParams(\(effect)) error: \(error)")
            }
        }
    }

    /// Update one param locally, send it to the daemon, and schedule
    /// a debounced disk write for the effect.
    func setParam(effect: String, name: String, value: Double) {
        // Splice-replace: rebuild the array with a new ParamSchema so
        // @Observable sees the change. Never mutate a struct in place.
        if var list = paramsByEffect[effect],
           let idx = list.firstIndex(where: { $0.name == name }) {
            var updated = list[idx]
            updated.value = value
            list[idx] = updated
            paramsByEffect[effect] = list
        }

        Task {
            do {
                try await client.setParamFor(
                    effect: effect, name: name, value: value,
                )
            } catch {
                logger.error("setParamFor error: \(error)")
            }
        }

        scheduleDiskWrite(for: effect)
    }

    /// Cancel debounce + clear disk + reset daemon + refresh cache.
    /// Order matters — see plan rationale. If any step after `clear`
    /// fails, disk is already in the "no overrides" state.
    func resetParams(effect: String) {
        pendingWrites[effect]?.cancel()
        pendingWrites[effect] = nil

        PersistenceStore.clear(effect: effect)

        Task {
            do {
                try await client.resetParamsFor(effect: effect)
                let fresh = try await client.getParamsFor(effect: effect)
                paramsByEffect[effect] = fresh
            } catch {
                logger.error("resetParams(\(effect)) error: \(error)")
            }
        }
    }

    /// Trailing debounce: write disk ~300ms after the last slider change.
    private func scheduleDiskWrite(for effect: String) {
        pendingWrites[effect]?.cancel()
        pendingWrites[effect] = Task { [weak self] in
            guard let self else { return }
            try? await Task.sleep(for: .milliseconds(Int(writeDebounceMillis)))
            if Task.isCancelled { return }
            self.flushDiskWrite(for: effect)
        }
    }

    private func flushDiskWrite(for effect: String) {
        guard let list = paramsByEffect[effect] else { return }
        // Only persist non-default values. A fully-default effect has
        // no override file — that's what clear() produces too.
        let overrides = list.reduce(into: [String: Double]()) { acc, p in
            if !p.isAtDefault { acc[p.name] = p.value }
        }
        if overrides.isEmpty {
            PersistenceStore.clear(effect: effect)
        } else {
            PersistenceStore.save(effect: effect, values: overrides)
        }
        pendingWrites[effect] = nil
    }

    // MARK: - State refresh

    private func refreshState() {
        Task {
            do {
                let status = try await client.getStatus()
                activeEffect = status.effect
                activeSidelight = status.sidelight
                isPaused = status.paused

                let list = try await client.listEffects()
                effects = list.effects
                sidelights = list.sidelights
                effectDescriptions = list.effect_descriptions ?? [:]
                logger.warning("refreshed: \(self.effects.count) effects, \(self.sidelights.count) sidelights")
            } catch {
                logger.error("refresh error: \(error)")
            }
        }
    }

    // MARK: - DaemonClientDelegate

    func daemonClientDidConnect(_ client: DaemonClient) {
        logger.warning("connected to daemon")
        isConnected = true
        refreshState()
    }

    func daemonClientDidDisconnect(_ client: DaemonClient) {
        logger.warning("disconnected from daemon")
        isConnected = false
        effects = []
        effectDescriptions = [:]
        sidelights = []
        activeEffect = nil
        activeSidelight = nil
        audioLevel = 0.0
        isPaused = false
    }

    func daemonClient(_ client: DaemonClient, didReceiveAudioLevel rms: Double) {
        audioLevel = rms
    }

    func daemonClient(_ client: DaemonClient, didChangeEffect name: String) {
        activeEffect = name
    }

    func daemonClient(_ client: DaemonClient, didChangeSidelight name: String) {
        activeSidelight = name
    }

    func daemonClient(_ client: DaemonClient, didChangePaused paused: Bool) {
        isPaused = paused
    }
}
