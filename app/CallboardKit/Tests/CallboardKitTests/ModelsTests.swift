@testable import CallboardKit
import Foundation
import Testing

@Suite("Models")
struct ModelsTests {
    private let decoder = Envelope.makeDecoder()

    private func isoDate(_ text: String) throws -> Date {
        try #require(ISO8601DateFormatter().date(from: text))
    }

    @Test func conversationsFixtureDecodes() throws {
        let snapshot = try decoder.decode(Snapshot.self, from: Fixture.data("admin-conversations"))
        #expect(snapshot.store == "/home/u/.local/share/callboard/callboard.sqlite")
        #expect(snapshot.cursor == 3)
        #expect(snapshot.conversations.map(\.id) == ["group:ops", "dm:enki:nanna"])
        let ops = snapshot.conversations[0]
        #expect(ops.kind == .group)
        #expect(ops.name == "ops")
        #expect(ops.subject == nil)
        #expect(ops.project == "bellhop")
        #expect(ops.createdBy == "enki")
        #expect(try ops.createdAt == isoDate("2026-11-14T09:00:00Z"))
        #expect(ops.members == ["enki", "nanna", "niels"])
        #expect(ops.messages == 2)
        #expect(ops.firstSeq == 2)
        #expect(ops.last?.seq == 3)
        #expect(ops.last?.id == "cb_000000000003")
        #expect(ops.last?.sender == "niels")
        #expect(ops.last?.preview == "on it")
        #expect(try ops.last?.createdAt == isoDate("2026-11-14T09:00:00Z"))
    }

    @Test func historyFixtureDecodes() throws {
        let page = try decoder.decode(HistoryPage.self, from: Fixture.data("admin-history"))
        #expect(page.conversation.id == "group:ops")
        #expect(page.more == false)
        #expect(page.messages.map(\.seq) == [2, 3])
        let reply = page.messages[1]
        #expect(reply.conversationId == "group:ops")
        #expect(reply.sender == "niels")
        #expect(reply.body == "on it")
        #expect(reply.bodyTruncated == false)
        #expect(try reply.createdAt == isoDate("2026-11-14T09:00:00Z"))
        #expect(reply.parentId == "cb_000000000002")
        #expect(page.messages[0].parentId == nil)
        #expect(page.messages[0].attachments.isEmpty)
    }

    @Test func snapshotLineDecodesWithItsEventKey() throws {
        let line = try watchLine(
            event: "snapshot",
            from: "admin-conversations",
            drop: ["schema_version", "status", "warnings"]
        )
        let snapshot = try decoder.decode(Snapshot.self, from: line)
        #expect(snapshot.cursor == 3)
        #expect(snapshot.conversations.count == 2)
    }

    @Test func messagesLineDecodesWithItsEventKey() throws {
        let history = try JSONSerialization.jsonObject(with: Fixture.data("admin-history")) as? [String: Any] ?? [:]
        let object: [String: Any] = [
            "event": "messages",
            "cursor": 3,
            "messages": history["messages"] ?? [],
            "conversations": [history["conversation"] ?? [:]]
        ]
        let batch = try decoder.decode(MessageBatch.self, from: JSONSerialization.data(withJSONObject: object))
        #expect(batch.cursor == 3)
        #expect(batch.messages.map(\.id) == ["cb_000000000002", "cb_000000000003"])
        #expect(batch.conversations.map(\.id) == ["group:ops"])
    }

    @Test func emptyConversationHasNoFirstSeqOrLast() throws {
        let summary = try decoder.decode(ConversationSummary.self, from: Data(summaryJSON(kind: "mail").utf8))
        #expect(summary.firstSeq == nil)
        #expect(summary.last == nil)
        #expect(summary.messages == 0)
    }

    @Test func unknownKindDecodesAsUnknown() throws {
        let summary = try decoder.decode(ConversationSummary.self, from: Data(summaryJSON(kind: "carrier-pigeon").utf8))
        #expect(summary.kind == .unknown)
    }

    @Test func knownKindsDecodeToTheirCases() throws {
        let kinds = try ["dm", "group", "mail", "topic"].map {
            try decoder.decode(ConversationSummary.self, from: Data(summaryJSON(kind: $0).utf8)).kind
        }
        #expect(kinds == [.dm, .group, .mail, .topic])
    }

    @Test func messageDecodesAttachmentsAndTruncation() throws {
        let json = """
        {"seq": 9, "id": "cb_9", "conversation_id": "dm:a:b", "sender": "a", "body": "long",
         "body_truncated": true, "parent_id": null, "created_at": "2026-11-14T09:00:00Z",
         "attachments": [{"id": "att_1", "filename": "log.txt", "media_type": "text/plain",
                          "size": 12, "path": "/tmp/log.txt"}]}
        """
        let message = try decoder.decode(ChatMessage.self, from: Data(json.utf8))
        #expect(message.bodyTruncated)
        let attachment = try #require(message.attachments.first)
        #expect(message.attachments.count == 1)
        #expect(attachment.id == "att_1")
        #expect(attachment.filename == "log.txt")
        #expect(attachment.mediaType == "text/plain")
        #expect(attachment.size == 12)
        #expect(attachment.path == "/tmp/log.txt")
    }

    private func summaryJSON(kind: String) -> String {
        """
        {"id": "x", "kind": "\(kind)", "name": null, "subject": null, "project": null,
         "created_by": "a", "created_at": "2026-11-14T09:00:00Z", "members": ["a"],
         "messages": 0, "first_seq": null, "last": null}
        """
    }

    private func watchLine(event: String, from fixture: String, drop: [String]) throws -> Data {
        var object = try JSONSerialization.jsonObject(with: Fixture.data(fixture)) as? [String: Any] ?? [:]
        drop.forEach { object[$0] = nil }
        object["event"] = event
        return try JSONSerialization.data(withJSONObject: object)
    }
}
