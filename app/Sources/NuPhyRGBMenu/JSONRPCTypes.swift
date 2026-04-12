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
    let effect_descriptions: [String: String]?
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

// MARK: - Param types

/// Wire format for a single param — dict value returned by the daemon.
private struct ParamSchemaWire: Decodable, Sendable {
    let value: Double
    let `default`: Double
    let min: Double
    let max: Double
    let description: String
    let order: Int
}

/// UI-facing param schema. Must be a struct so `@Observable` observation
/// propagates when spliced into an array on AppState.
struct ParamSchema: Identifiable, Sendable, Equatable {
    let name: String
    var value: Double
    let defaultValue: Double
    let min: Double
    let max: Double
    let description: String
    let order: Int

    var id: String { name }

    var isAtDefault: Bool {
        // Tolerate float noise from slider drag round-trips.
        abs(value - defaultValue) < 1e-9
    }
}

/// Convert a `{name: wireSchema}` map into a sorted `[ParamSchema]`.
enum ParamMapDecoder {
    fileprivate static func convert(
        _ map: [String: ParamSchemaWire],
    ) -> [ParamSchema] {
        map
            .map { name, wire in
                ParamSchema(
                    name: name,
                    value: wire.value,
                    defaultValue: wire.`default`,
                    min: wire.min,
                    max: wire.max,
                    description: wire.description,
                    order: wire.order,
                )
            }
            .sorted { lhs, rhs in
                if lhs.order != rhs.order { return lhs.order < rhs.order }
                return lhs.name < rhs.name
            }
    }

    static func decode(_ data: Data) throws -> [ParamSchema] {
        let map = try JSONDecoder().decode([String: ParamSchemaWire].self, from: data)
        return convert(map)
    }
}

/// Response payload for `set_effect_and_get_params`.
struct SetEffectAndGetParamsResult: Sendable {
    let name: String
    let params: [ParamSchema]

    static func decode(_ data: Data) throws -> SetEffectAndGetParamsResult {
        struct Wire: Decodable {
            let name: String
            let params: [String: ParamSchemaWire]
        }
        let wire = try JSONDecoder().decode(Wire.self, from: data)
        return SetEffectAndGetParamsResult(
            name: wire.name,
            params: ParamMapDecoder.convert(wire.params),
        )
    }
}
