import Foundation

public protocol CallboardReading: Sendable {
    func history(conversationId: String, before: Int64?, limit: Int) async throws -> HistoryPage
}

public struct CallboardClient: CallboardReading {
    private let command: CallboardCommand
    private let timeout: Duration

    public init(command: CallboardCommand, timeout: Duration = .seconds(35)) {
        self.command = command
        self.timeout = timeout
    }

    public func history(conversationId: String, before: Int64?, limit: Int) async throws -> HistoryPage {
        let before = before.map { ["--before", String($0)] } ?? []
        let output = try await ProcessRunner.run(
            command,
            arguments: ["admin", "history", conversationId, "--limit", String(limit)] + before + ["--json"],
            name: "admin history",
            timeout: timeout
        )
        return try Envelope.decode(HistoryPage.self, from: output, command: "admin history")
    }
}
