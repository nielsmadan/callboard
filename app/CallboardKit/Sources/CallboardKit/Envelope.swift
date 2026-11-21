import Foundation

enum Envelope {
    static let supportedSchema = 1

    static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    static func decode<Value: Decodable>(
        _: Value.Type,
        from output: ProcessOutput,
        command: String
    ) throws -> Value {
        switch try reply(Value.self, from: output.stdout, command: command) {
        case let .ok(value):
            value
        case let .failed(code, message):
            throw CallboardError.commandFailed(
                command: command,
                exitCode: output.exitCode,
                code: code,
                message: message
            )
        case nil:
            throw unreadable(output, command: command)
        }
    }

    static func reply<Value: Decodable>(_: Value.Type, from data: Data, command: String) throws -> Reply<Value>? {
        let decoder = makeDecoder()
        guard let header = try? decoder.decode(Header.self, from: data) else { return nil }
        guard header.schemaVersion == supportedSchema else {
            throw CallboardError.unsupportedSchema(header.schemaVersion)
        }
        if header.status == "error" {
            return .failed(code: header.error?.code, message: header.error?.message ?? "unknown error")
        }
        do {
            return try .ok(decoder.decode(Value.self, from: data))
        } catch {
            throw CallboardError.malformedOutput(command: command, detail: String(describing: error))
        }
    }

    enum Reply<Value> {
        case ok(Value)
        case failed(code: String?, message: String)
    }

    private static func unreadable(_ output: ProcessOutput, command: String) -> CallboardError {
        guard output.exitCode != 0 else {
            return .malformedOutput(command: command, detail: "stdout is not a callboard envelope")
        }
        return .commandFailed(
            command: command,
            exitCode: output.exitCode,
            code: output.exitCode == 2 && !output.diedBySignal ? "usage" : nil,
            message: output.standardErrorTail
        )
    }

    private struct Header: Decodable {
        let schemaVersion: Int
        let status: String
        let error: Failure?
    }

    private struct Failure: Decodable {
        let code: String?
        let message: String?
    }
}

extension ProcessOutput {
    var standardErrorTail: String {
        StandardError.tail(of: stderr)
    }
}
