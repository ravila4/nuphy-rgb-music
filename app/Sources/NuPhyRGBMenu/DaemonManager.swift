import AppKit
import os

private let logger = Logger(subsystem: "com.nuphy-rgb.menu", category: "DaemonMgr")

/// Manages the lifecycle of the `nuphy-rgb` daemon process.
@MainActor
final class DaemonManager {
    enum State: Sendable {
        case stopped
        case starting
        case running
        case stopping
    }

    private(set) var state: State = .stopped
    private var process: Process?
    private var socketPath: String?
    private var terminationObserver: (any NSObjectProtocol)?

    /// Start the daemon. Parses stdout for the IPC socket path.
    func start() throws {
        guard state == .stopped else { return }
        state = .starting

        let proc = Process()

        if let bundled = Bundle.main.url(forAuxiliaryExecutable: "NuPhyDaemon") {
            logger.warning("using bundled daemon: \(bundled.path, privacy: .public)")
            proc.executableURL = bundled
            proc.arguments = []
        } else {
            // Dev mode: use uv run from project directory
            logger.warning("dev mode: using uv run")
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            proc.arguments = ["uv", "run", "nuphy-rgb"]
            proc.currentDirectoryURL = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent()  // NuPhyRGBMenu/
                .deletingLastPathComponent()  // Sources/
                .deletingLastPathComponent()  // app/
                .deletingLastPathComponent()  // project root
        }

        // Force unbuffered Python output so pipes capture immediately
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        proc.environment = env

        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        proc.standardOutput = stdoutPipe
        proc.standardError = stderrPipe

        proc.terminationHandler = { [weak self] proc in
            let code = proc.terminationStatus
            Task { @MainActor in
                logger.warning("daemon exited (code=\(code))")
                self?.handleTermination()
            }
        }

        // Ensure daemon dies when the app exits (no orphans)
        proc.qualityOfService = .userInitiated
        try proc.run()
        process = proc
        state = .running
        logger.warning("started daemon (pid=\(proc.processIdentifier))")

        // Kill daemon when the app exits (no orphans)
        let pid = proc.processIdentifier
        terminationObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil,
            queue: .main
        ) { _ in
            logger.warning("app terminating, killing daemon pid=\(pid)")
            kill(pid, SIGTERM)
        }

        // Log stderr continuously in background
        let errHandle = stderrPipe.fileHandleForReading
        Task.detached {
            do {
                for try await line in errHandle.bytes.lines {
                    logger.warning("stderr: \(line, privacy: .public)")
                }
            } catch {
                logger.error("stderr pipe closed: \(error)")
            }
        }

        // Parse stdout continuously for socket path
        let outHandle = stdoutPipe.fileHandleForReading
        Task.detached { [weak self] in
            do {
                for try await line in outHandle.bytes.lines {
                    logger.warning("stdout: \(line, privacy: .public)")
                    if line.contains("IPC:") {
                        let path = line.components(separatedBy: "IPC:").last?
                            .trimmingCharacters(in: .whitespaces) ?? ""
                        if !path.isEmpty {
                            await self?.setSocketPath(path)
                        }
                    }
                }
            } catch {
                logger.error("stdout pipe error: \(error)")
            }
        }
    }

    /// Stop the daemon via the IPC `quit` command, with a Process.terminate fallback.
    func stop(via client: DaemonClient) async {
        guard state == .running else { return }
        state = .stopping

        do {
            try await client.quit()
            try await Task.sleep(for: .seconds(1))
        } catch {}

        if let proc = process, proc.isRunning {
            proc.terminate()
        }

        cleanup()
    }

    /// The discovered socket path (from daemon stdout), or the default.
    var effectiveSocketPath: String {
        socketPath ?? DaemonClient.defaultSocketPath()
    }

    /// Check if a daemon is already running (socket probe).
    nonisolated func detectRunning() -> Bool {
        DaemonClient.probe()
    }

    /// Kill any existing daemon via quit RPC, then wait for socket to go away.
    func killExisting(via client: DaemonClient) async {
        guard detectRunning() else { return }
        logger.warning("killing existing daemon")
        client.connect()
        do {
            try await client.quit()
        } catch {}
        client.disconnect()
        // Wait for socket to disappear
        for _ in 0..<20 {
            try? await Task.sleep(for: .milliseconds(250))
            if !detectRunning() { return }
        }
        logger.warning("existing daemon did not exit cleanly")
    }

    private func setSocketPath(_ path: String) {
        socketPath = path
    }

    private func handleTermination() {
        cleanup()
    }

    private func cleanup() {
        if let obs = terminationObserver {
            NotificationCenter.default.removeObserver(obs)
            terminationObserver = nil
        }
        process = nil
        socketPath = nil
        state = .stopped
    }
}
