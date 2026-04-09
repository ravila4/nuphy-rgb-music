import Foundation

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
    var audioLevel: Double = 0.0

    var statusIcon: String {
        client.isConnected ? "waveform" : "waveform.slash"
    }

    init() {
        client.delegate = self
        connectOrStart()
    }

    // MARK: - Connection

    func connectOrStart() {
        if manager.detectRunning() {
            print("[AppState] daemon already running, connecting...")
            client.connect()
        } else {
            print("[AppState] no daemon found, starting...")
            startDaemon()
        }
    }

    func startDaemon() {
        do {
            try manager.start()
            print("[AppState] daemon started, waiting for socket...")
            Task {
                for _ in 0..<20 {  // up to 5 seconds
                    try await Task.sleep(for: .milliseconds(250))
                    if DaemonClient.probe(socketPath: manager.effectiveSocketPath) {
                        print("[AppState] socket ready, connecting")
                        client.connect(socketPath: manager.effectiveSocketPath)
                        return
                    }
                }
                print("[AppState] timed out waiting for daemon socket")
            }
        } catch {
            print("[AppState] failed to start daemon: \(error)")
        }
    }

    func stopDaemon() {
        Task {
            await manager.stop(via: client)
        }
    }

    // MARK: - Effect switching

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

                let list = try await client.listEffects()
                effects = list.effects
                sidelights = list.sidelights
                print("[AppState] refreshed: \(effects.count) effects, \(sidelights.count) sidelights")
            } catch {
                print("[AppState] refresh error: \(error)")
            }
        }
    }

    // MARK: - DaemonClientDelegate

    func daemonClientDidConnect(_ client: DaemonClient) {
        print("[AppState] connected to daemon")
        refreshState()
    }

    func daemonClientDidDisconnect(_ client: DaemonClient) {
        print("[AppState] disconnected from daemon")
        effects = []
        sidelights = []
        activeEffect = nil
        activeSidelight = nil
        audioLevel = 0.0
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
}
