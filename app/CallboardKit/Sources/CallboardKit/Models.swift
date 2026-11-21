import Foundation

public enum ConversationKind: String, Sendable, Equatable, Decodable {
    case dm
    case group
    case mail
    case topic
    case unknown

    public init(from decoder: any Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: raw) ?? .unknown
    }
}

public struct LastMessage: Decodable, Sendable, Equatable {
    public let seq: Int64
    public let id: String
    public let sender: String
    public let createdAt: Date
    public let preview: String
}

public struct ConversationSummary: Decodable, Sendable, Equatable, Identifiable {
    public let id: String
    public let kind: ConversationKind
    public let name: String?
    public let subject: String?
    public let project: String?
    public let createdBy: String
    public let createdAt: Date
    public let members: [String]
    public let messages: Int
    public let firstSeq: Int64?
    public let last: LastMessage?
}

public struct AttachmentInfo: Decodable, Sendable, Equatable, Identifiable {
    public let id: String
    public let filename: String
    public let mediaType: String
    public let size: Int64
    public let path: String
}

public struct ChatMessage: Decodable, Sendable, Equatable, Identifiable {
    public let seq: Int64
    public let id: String
    public let conversationId: String
    public let sender: String
    public let body: String
    public let bodyTruncated: Bool
    public let parentId: String?
    public let createdAt: Date
    public let attachments: [AttachmentInfo]
}

public struct Snapshot: Decodable, Sendable, Equatable {
    public let store: String
    public let cursor: Int64
    public let conversations: [ConversationSummary]
}

public struct MessageBatch: Decodable, Sendable, Equatable {
    public let cursor: Int64
    public let messages: [ChatMessage]
    public let conversations: [ConversationSummary]
}

public struct HistoryPage: Decodable, Sendable, Equatable {
    public let store: String
    public let conversation: ConversationSummary
    public let messages: [ChatMessage]
    public let more: Bool
}

public enum WatchEvent: Sendable, Equatable {
    case snapshot(Snapshot)
    case messages(MessageBatch)
}
