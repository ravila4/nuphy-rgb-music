import Foundation
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
    var sidelights: [String] = []
    var activeEffect: String?
    var activeSidelight: String?
    var isConnected = false
    var audioLevel: Double = 0.0
    var isPaused = false

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

    // MARK: - Effect switching

    func togglePause() {
        Task {
            do {
                let result = try await client.setPaused(!isPaused)
                isPaused = result.paused
            } catch {
                print("[AppState] setPaused error: \(error)")
            }
        }
    }

    func selectEffect(_ name: String) {
        Task {
            do {
                let result = try await client.setEffect(name: name)
                activeEffect = result.name
            } catch {
                print("[AppState] setEffect error: \(error)")
            }
        }
    }

    func selectSidelight(_ name: String) {
        Task {
            do {
                let result = try await client.setSidelight(name: name)
                activeSidelight = result.name
            } catch {
                print("[AppState] setSidelight error: \(error)")
            }
        }
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
