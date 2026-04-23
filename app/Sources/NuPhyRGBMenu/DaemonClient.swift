import Foundation
import os

private let log = Logger(subsystem: "com.nuphy-rgb.menu", category: "Client")

/// Callback types for push notifications from the daemon.
@MainActor
protocol DaemonClientDelegate: AnyObject {
    func daemonClient(_ client: DaemonClient, didReceiveAudioLevel rms: Double)
    func daemonClient(_ client: DaemonClient, didChangeEffect name: String)
    func daemonClient(_ client: DaemonClient, didChangeSidelight name: String)
    func daemonClient(_ client: DaemonClient, didChangePaused paused: Bool)
    func daemonClient(_ client: DaemonClient, didChangeShuffle enabled: Bool)
    func daemonClientDidConnect(_ client: DaemonClient)
    func daemonClientDidDisconnect(_ client: DaemonClient)
}

/// JSON-RPC 2.0 client over Unix domain socket.
///
/// All public methods run on `@MainActor`. Socket I/O is dispatched
/// to a serial background queue; results are marshalled back to main.
@MainActor
final class DaemonClient {
    weak var delegate: DaemonClientDelegate?

    private(set) var isConnected = false
    private var fd: Int32 = -1
    private var writeHandle: FileHandle?
    private var nextId = 1
    private var pending: [Int: (Result<Data, Error>) -> Void] = [:]
    private var readTask: Task<Void, Never>?

    // MARK: - Connection

    func connect(socketPath: String? = nil) {
        guard !isConnected else { return }

        let path = socketPath ?? Self.defaultSocketPath()
        fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { return }

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = path.utf8CString
        guard pathBytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else {
            close(fd)
            fd = -1
            return
        }
        withUnsafeMutablePointer(to: &addr.sun_path) { ptr in
            ptr.withMemoryRebound(to: CChar.self, capacity: pathBytes.count) { dst in
                pathBytes.withUnsafeBufferPointer { src in
                    _ = memcpy(dst, src.baseAddress!, src.count)
                }
            }
        }

        let addrLen = socklen_t(MemoryLayout<sockaddr_un>.size)
        let connectResult = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockPtr in
                Foundation.connect(fd, sockPtr, addrLen)
            }
        }
        guard connectResult == 0 else {
            let err = errno
            log.error("connect failed: errno=\(err) (\(String(cString: strerror(err))))")
            close(fd)
            fd = -1
            return
        }

        // Separate file descriptors for read and write to avoid conflicts.
        let readFd = dup(fd)
        guard readFd >= 0 else {
            log.error("dup failed")
            close(fd)
            fd = -1
            return
        }

        writeHandle = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
        isConnected = true
        log.info("connected to \(path)")
        startReadLoop(readFd: readFd)
        delegate?.daemonClientDidConnect(self)
    }

    func disconnect() {
        guard isConnected else { return }
        readTask?.cancel()
        readTask = nil
        writeHandle = nil
        close(fd)
        fd = -1
        isConnected = false
        // Fail all pending requests
        let pendingCopy = pending
        pending.removeAll()
        for (_, completion) in pendingCopy {
            completion(.failure(DaemonClientError.disconnected))
        }
        delegate?.daemonClientDidDisconnect(self)
    }

    // MARK: - RPC Methods

    func getStatus() async throws -> StatusResult {
        let data = try await sendRequest(method: "get_status")
        return try JSONDecoder().decode(StatusResult.self, from: data)
    }

    func listEffects() async throws -> ListEffectsResult {
        let data = try await sendRequest(method: "list_effects")
        return try JSONDecoder().decode(ListEffectsResult.self, from: data)
    }

    func setEffect(name: String) async throws -> EffectResult {
        let data = try await sendRequest(method: "set_effect", params: ["name": name])
        return try JSONDecoder().decode(EffectResult.self, from: data)
    }

    func setSidelight(name: String) async throws -> EffectResult {
        let data = try await sendRequest(method: "set_sidelight", params: ["name": name])
        return try JSONDecoder().decode(EffectResult.self, from: data)
    }

    func setPaused(_ paused: Bool) async throws -> PausedResult {
        let data = try await sendRequest(method: "set_paused", params: ["paused": paused])
        return try JSONDecoder().decode(PausedResult.self, from: data)
    }

    func setShuffle(_ enabled: Bool) async throws -> ShuffleResult {
        let data = try await sendRequest(
            method: "set_shuffle",
            params: ["enabled": enabled],
        )
        return try JSONDecoder().decode(ShuffleResult.self, from: data)
    }

    func quit() async throws {
        _ = try await sendRequest(method: "quit")
    }

    // MARK: - Param RPCs

    func getParamsFor(effect: String) async throws -> [ParamSchema] {
        let data = try await sendRequest(
            method: "get_params_for",
            params: ["name": effect],
        )
        return try ParamMapDecoder.decode(data)
    }

    func setParamFor(effect: String, name: String, value: Double) async throws {
        _ = try await sendRequest(
            method: "set_param_for",
            params: ["name": effect, "param": name, "value": value],
        )
    }

    func resetParamsFor(effect: String) async throws {
        _ = try await sendRequest(
            method: "reset_params_for",
            params: ["name": effect],
        )
    }

    func setEffectAndGetParams(
        name: String,
    ) async throws -> SetEffectAndGetParamsResult {
        let data = try await sendRequest(
            method: "set_effect_and_get_params",
            params: ["name": name],
        )
        return try SetEffectAndGetParamsResult.decode(data)
    }

    // MARK: - Socket path

    nonisolated static func defaultSocketPath() -> String {
        let tmpdir = ProcessInfo.processInfo.environment["TMPDIR"] ?? "/tmp"
        return "\(tmpdir)/nuphy-rgb/control.sock"
    }

    /// Probe whether a daemon is listening at the given socket path.
    nonisolated static func probe(socketPath: String? = nil) -> Bool {
        let path = socketPath ?? defaultSocketPath()

        let probeFd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard probeFd >= 0 else { return false }
        defer { close(probeFd) }

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = path.utf8CString
        guard pathBytes.count <= MemoryLayout.size(ofValue: addr.sun_path) else {
            return false
        }
        withUnsafeMutablePointer(to: &addr.sun_path) { ptr in
            ptr.withMemoryRebound(to: CChar.self, capacity: pathBytes.count) { dst in
                pathBytes.withUnsafeBufferPointer { src in
                    _ = memcpy(dst, src.baseAddress!, src.count)
                }
            }
        }

        let addrLen = socklen_t(MemoryLayout<sockaddr_un>.size)
        let result = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockPtr in
                Foundation.connect(probeFd, sockPtr, addrLen)
            }
        }
        return result == 0
    }

    // MARK: - Internal

    private func sendRequest(method: String, params: [String: any Sendable]? = nil) async throws -> Data {
        guard isConnected, let handle = writeHandle else {
            throw DaemonClientError.notConnected
        }

        let id = nextId
        nextId += 1

        let request = JSONRPCRequest(method: method, params: params, id: id)
        let data = try request.toData()
        log.debug("sendRequest: \(method, privacy: .public) id=\(id) payload=\(String(data: data, encoding: .utf8) ?? "nil", privacy: .public)")
        let payload = data + Data([0x0A])  // newline-delimited JSON

        return try await withCheckedThrowingContinuation { continuation in
            pending[id] = { result in
                continuation.resume(with: result)
            }

            do {
                try handle.write(contentsOf: payload)
            } catch {
                // Guard against double-resume if disconnect() already drained pending
                if pending.removeValue(forKey: id) != nil {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private func startReadLoop(readFd: Int32) {
        let readHandle = FileHandle(fileDescriptor: readFd, closeOnDealloc: true)

        readTask = Task.detached { [weak self] in
            log.info("read loop started on fd=\(readFd)")
            var buffer = Data()

            while !Task.isCancelled {
                let data = readHandle.availableData
                if data.isEmpty { break }
                buffer.append(data)

                // Process complete lines
                while let newlineRange = buffer.range(of: Data([0x0A])) {
                    let lineData = buffer.subdata(in: buffer.startIndex..<newlineRange.lowerBound)
                    buffer.removeSubrange(buffer.startIndex...newlineRange.lowerBound)

                    guard let message = JSONRPCMessage.parse(lineData) else { continue }
                    await self?.handleMessage(message)
                }
            }

            log.info("read loop ended")

            if let self = self {
                await self.handleReadLoopEnded()
            }
        }
    }

    @MainActor
    private func handleMessage(_ message: JSONRPCMessage) {
        log.debug("handleMessage: \(String(describing: message), privacy: .public)")
        switch message {
        case .response(let id, let resultData):
            guard let completion = pending.removeValue(forKey: id) else { return }
            completion(.success(resultData))

        case .error(let id, let code, let message):
            guard let completion = pending.removeValue(forKey: id) else { return }
            completion(.failure(DaemonClientError.rpcError(code: code, message: message)))

        case .notification(let method, let paramsData):
            handleNotification(method: method, paramsData: paramsData)
        }
    }

    @MainActor
    private func handleNotification(method: String, paramsData: Data) {
        let decoder = JSONDecoder()
        switch method {
        case "audio_level":
            if let level = try? decoder.decode(AudioLevelParams.self, from: paramsData) {
                delegate?.daemonClient(self, didReceiveAudioLevel: level.raw_rms)
            }
        case "effect_changed":
            if let effect = try? decoder.decode(EffectResult.self, from: paramsData) {
                delegate?.daemonClient(self, didChangeEffect: effect.name)
            }
        case "sidelight_changed":
            if let sidelight = try? decoder.decode(EffectResult.self, from: paramsData) {
                delegate?.daemonClient(self, didChangeSidelight: sidelight.name)
            }
        case "paused_changed":
            if let result = try? decoder.decode(PausedResult.self, from: paramsData) {
                delegate?.daemonClient(self, didChangePaused: result.paused)
            }
        case "shuffle_changed":
            if let result = try? decoder.decode(ShuffleResult.self, from: paramsData) {
                delegate?.daemonClient(self, didChangeShuffle: result.enabled)
            }
        default:
            break
        }
    }

    @MainActor
    private func handleReadLoopEnded() {
        if isConnected {
            disconnect()
        }
    }
}

enum DaemonClientError: Error, LocalizedError {
    case notConnected
    case disconnected
    case invalidResponse
    case rpcError(code: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notConnected: "Not connected to daemon"
        case .disconnected: "Disconnected from daemon"
        case .invalidResponse: "Invalid response from daemon"
        case .rpcError(_, let message): message
        }
    }
}
