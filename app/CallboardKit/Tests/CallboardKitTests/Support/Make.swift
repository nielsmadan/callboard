import CallboardKit
import Foundation

typealias JSONObject = [String: Any]

enum Make {
    static let store = "/stores/main/callboard.sqlite"
    static let createdAt = "2026-11-14T09:00:00Z"

    static func conversation(
        _ id: String,
        name: String? = nil,
        members: [String] = ["enki", "nanna"],
        seqs: [Int64] = [],
        firstSeq: Int64? = nil,
        sender: String = "enki",
        preview: String = "hello"
    ) -> JSONObject {
        let last: Any = seqs.last.map { seq -> JSONObject in
            ["seq": seq, "id": "cb_\(seq)", "sender": sender, "created_at": createdAt, "preview": preview]
        } ?? NSNull()
        return [
            "id": id, "kind": String(id.prefix { $0 != ":" }), "name": name ?? NSNull(), "subject": NSNull(),
            "project": NSNull(), "created_by": "enki", "created_at": createdAt, "members": members,
            "messages": seqs.count, "first_seq": (firstSeq ?? seqs.first).map { $0 as Any } ?? NSNull(), "last": last
        ]
    }

    static func message(_ seq: Int64, in conversationId: String, body: String = "body", parent: String? = nil)
        -> JSONObject {
        [
            "seq": seq, "id": "cb_\(seq)", "conversation_id": conversationId, "sender": "enki", "body": body,
            "body_truncated": false, "parent_id": parent ?? NSNull(), "created_at": createdAt, "attachments": []
        ]
    }

    static func summary(_ object: JSONObject) -> ConversationSummary {
        decode(object)
    }

    static func chatMessage(_ object: JSONObject) -> ChatMessage {
        decode(object)
    }

    static func snapshot(_ conversations: [JSONObject], store: String = Make.store) -> WatchEvent {
        .snapshot(decode(["store": store, "cursor": 0, "conversations": conversations]))
    }

    static func batch(_ messages: [JSONObject], touching conversations: [JSONObject]) -> WatchEvent {
        .messages(decode(["cursor": messages.last?["seq"] ?? 0, "messages": messages, "conversations": conversations]))
    }

    static func page(_ conversation: JSONObject, _ messages: [JSONObject], more: Bool = false) -> HistoryPage {
        decode(["store": store, "conversation": conversation, "messages": messages, "more": more])
    }

    private static func decode<T: Decodable>(_ object: JSONObject) -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return try! decoder.decode(T.self, from: JSONSerialization.data(withJSONObject: object))
    }
}
