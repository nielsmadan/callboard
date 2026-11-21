import Foundation

public struct ViewMark: Codable, Sendable, Equatable {
    public let firstSeq: Int64?
    public let messages: Int
}

@MainActor public protocol ViewTracker: AnyObject {
    func begin(store: String, snapshot: [ConversationSummary])
    func newCount(for conversation: ConversationSummary) -> Int
    func markViewed(_ conversation: ConversationSummary)
}

@MainActor public final class LocalViewTracker: ViewTracker {
    private struct Saved: Codable {
        var marks: [String: [String: ViewMark]] = [:]
        var baselines: Set<String> = []
    }

    private let defaults: UserDefaults
    private let key: String
    private var saved: Saved
    private var store: String?

    public init(defaults: UserDefaults, key: String = "viewMarks") {
        self.defaults = defaults
        self.key = key
        saved = defaults.data(forKey: key).flatMap { try? JSONDecoder().decode(Saved.self, from: $0) } ?? Saved()
    }

    public func begin(store: String, snapshot: [ConversationSummary]) {
        self.store = store
        guard !saved.baselines.contains(store), !snapshot.isEmpty else { return }
        saved.baselines.insert(store)
        saved.marks[store, default: [:]].merge(snapshot.map { ($0.id, Self.mark(of: $0)) }) { $1 }
        persist()
    }

    public func newCount(for conversation: ConversationSummary) -> Int {
        guard let store else { return 0 }
        return Self.newCount(
            for: conversation,
            mark: saved.marks[store]?[conversation.id],
            hasBaseline: saved.baselines.contains(store)
        )
    }

    public func markViewed(_ conversation: ConversationSummary) {
        guard let store else { return }
        saved.marks[store, default: [:]][conversation.id] = Self.mark(of: conversation)
        persist()
    }

    static func newCount(for conversation: ConversationSummary, mark: ViewMark?, hasBaseline: Bool) -> Int {
        guard let mark else { return hasBaseline ? conversation.messages : 0 }
        guard mark.firstSeq == conversation.firstSeq else { return conversation.messages }
        return max(0, conversation.messages - mark.messages)
    }

    private static func mark(of conversation: ConversationSummary) -> ViewMark {
        ViewMark(firstSeq: conversation.firstSeq, messages: conversation.messages)
    }

    private func persist() {
        guard let data = try? JSONEncoder().encode(saved) else { return }
        defaults.set(data, forKey: key)
    }
}
