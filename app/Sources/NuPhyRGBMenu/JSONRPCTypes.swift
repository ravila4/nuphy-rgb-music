import Foundation

// MARK: - Outgoing

struct JSONRPCRequest: Sendable {
    let method: String
    let params: [String: any Sendable]?
    let id: Int

    func toData() throws -> Data {
        var obj: [String: Any] = ["jsonrpc": "2.0", "method": method, "id": id]
        if let p = params { obj["params"] = p }
        return try JSONSerialization.data(withJSONObject: obj)
    }
}

// MARK: - Incoming

/// A parsed incoming JSON-RPC message.
enum JSONRPCMessage: Sendable {
    case response(id: Int, result: Data)
    case error(id: Int, code: Int, message: String)
    case notification(method: String, params: Data)

    /// Parse a raw JSON line into a typed message.
    static func parse(_ data: Data) -> JSONRPCMessage? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }

        if let id = obj["id"] as? Int {
            // Response
            if let errorObj = obj["error"] as? [String: Any],
               let code = errorObj["code"] as? Int,
               let message = errorObj["message"] as? String {
                return .error(id: id, code: code, message: message)
            }
            if let result = obj["result"] {
                let resultData = (try? JSONSerialization.data(withJSONObject: result)) ?? Data()
                return .response(id: id, result: resultData)
            }
            return nil
        } else if let method = obj["method"] as? String {
            // Notification
            let paramsData: Data
            if let params = obj["params"] {
                paramsData = (try? JSONSerialization.data(withJSONObject: params)) ?? Data()
            } else {
                paramsData = Data("{}".utf8)
            }
            return .notification(method: method, params: paramsData)
        }

        return nil
    }
}

// MARK: - JSON-RPC Error

struct JSONRPCError: Decodable, Sendable {
    let code: Int
    let message: String
}

// MARK: - Result types

struct StatusResult: Decodable, Sendable {
    let effect: String
    let sidelight: String?
    let running: Bool
    let paused: Bool
}

struct PausedResult: Decodable, Sendable {
    let paused: Bool
}

struct ListEffectsResult: Decodable, Sendable {
    let effects: [String]
    let sidelights: [String]
}

struct EffectResult: Decodable, Sendable {
    let name: String
}

struct AudioLevelParams: Decodable, Sendable {
    let raw_rms: Double
}

struct QuitResult: Decodable, Sendable {
    let ok: Bool
}
