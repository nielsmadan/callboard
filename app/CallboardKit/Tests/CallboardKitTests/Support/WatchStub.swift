import CallboardKit
import Foundation

struct WatchStub {
    let stub: CallboardStub

    var command: CallboardCommand {
        stub.command
    }

    var arguments: [String] {
        stub.arguments
    }

    var status: [String] {
        let text = (try? String(contentsOf: stub.directory.appending(path: "status"), encoding: .utf8)) ?? ""
        return text.split(separator: "\n").map(String.init)
    }

    var pids: [pid_t] {
        let text = (try? String(contentsOf: stub.directory.appending(path: "pid"), encoding: .utf8)) ?? ""
        return text.split(separator: "\n").compactMap { pid_t($0) }
    }

    var isAlive: Bool {
        pids.first.map { kill($0, 0) == 0 } ?? false
    }

    static func with<Result>(
        lines: [String] = [],
        script: String,
        environment: [String: String] = [:],
        _ body: (WatchStub) async throws -> Result
    ) async throws -> Result {
        let preamble = """
        DIR="$(dirname "$0")"
        echo $$ > "$DIR/pid"
        trap 'echo exited >> "$DIR/status"' EXIT
        """
        return try await CallboardStub.with(script: preamble + "\n" + script, environment: environment) { stub in
            let watch = WatchStub(stub: stub)
            try lines.map { $0 + "\n" }.joined().write(
                to: stub.directory.appending(path: "lines"),
                atomically: true,
                encoding: .utf8
            )
            defer {
                for pid in watch.pids {
                    kill(pid, SIGKILL)
                }
            }
            return try await body(watch)
        }
    }

    static func until(_ deadline: Duration, _ condition: () -> Bool) async -> Bool {
        let end = ContinuousClock.now + deadline
        while ContinuousClock.now < end {
            if condition() { return true }
            try? await Task.sleep(for: .milliseconds(20))
        }
        return condition()
    }
}

enum WatchLine {
    static func envelope(_ fields: [String: Any]) throws -> String {
        let base: [String: Any] = ["schema_version": 1, "status": "ok", "warnings": [String]()]
        let object = base.merging(fields) { $1 }
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        return String(decoding: data, as: UTF8.self)
    }

    static func snapshot() throws -> String {
        var fields = try fixture("admin-conversations")
        fields["event"] = "snapshot"
        return try envelope(fields)
    }

    static func messages() throws -> String {
        let history = try fixture("admin-history")
        return try envelope([
            "event": "messages",
            "cursor": 3,
            "messages": history["messages"] ?? [],
            "conversations": [history["conversation"] ?? [:]]
        ])
    }

    static func golden(_ name: String) throws -> String {
        try String(decoding: Fixture.data(name), as: UTF8.self).trimmingCharacters(in: .newlines)
    }

    static func empty(cursor: Int) throws -> String {
        try envelope(["event": "messages", "cursor": cursor, "messages": [Any](), "conversations": [Any]()])
    }

    private static func fixture(_ name: String) throws -> [String: Any] {
        let object = try JSONSerialization.jsonObject(with: Fixture.data(name))
        return (object as? [String: Any]) ?? [:]
    }
}
