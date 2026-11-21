import Foundation
import Observation

public enum FeedState: Equatable, Sendable {
    case starting
    case live
    case reconnecting(String)
    case failed(String)
}

public struct ThreadState: Equatable, Sendable {
    public var messages: [ChatMessage]
    public var more: Bool
    public var loading: Bool
    public var error: String?

    static let empty = ThreadState(messages: [], more: false, loading: false, error: nil)
}

@MainActor @Observable public final class ChatStore {
    public nonisolated static func nextAttempt(_ attempt: Int, upFor: Duration?) -> Int {
        guard let upFor, upFor >= stableAfter else { return attempt }
        return 0
    }

    public nonisolated static let defaultBackoff: @Sendable (Int) -> Duration = { attempt in
        .seconds(min(30, 1 << min(attempt, 5)))
    }

    private static let pageSize = 50
    private nonisolated static let stableAfter = Duration.seconds(30)

    public private(set) var store: String?
    public private(set) var conversations: [ConversationSummary] = []
    public private(set) var state: FeedState = .starting
    public private(set) var selectedId: String?
    public private(set) var thread = ThreadState.empty
    public var isViewing = false {
        didSet {
            if isViewing, !oldValue { markSelectedViewed() }
        }
    }

    private var newCounts: [String: Int] = [:]

    @ObservationIgnored private let reader: any CallboardReading
    @ObservationIgnored private let source: any EventSource
    @ObservationIgnored private let tracker: any ViewTracker
    @ObservationIgnored private let backoff: @Sendable (Int) -> Duration
    @ObservationIgnored private let threadLimit: Int
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var pagingEpoch = 0
    @ObservationIgnored private var loadedLimit: Int
    @ObservationIgnored private var reload: Task<Void, Never>?

    public init(
        reader: any CallboardReading,
        source: any EventSource,
        tracker: any ViewTracker,
        backoff: @escaping @Sendable (Int) -> Duration = ChatStore.defaultBackoff,
        threadLimit: Int = 1000
    ) {
        self.reader = reader
        self.source = source
        self.tracker = tracker
        self.backoff = backoff
        self.threadLimit = threadLimit
        loadedLimit = threadLimit
    }

    public var chatConversations: [ConversationSummary] {
        conversations.filter(\.kind.isChat)
    }

    public var totalNew: Int {
        chatConversations.reduce(0) { $0 + newCount(for: $1.id) }
    }

    public func newCount(for conversationId: String) -> Int {
        newCounts[conversationId] ?? 0
    }

    public func sections(mode: ListMode) -> [RowSection] {
        ListArrangement.sections(conversations, newCounts: newCounts, mode: mode)
    }

    public func run() async {
        let clock = ContinuousClock()
        var attempt = 0
        defer { reload?.cancel() }
        while !Task.isCancelled {
            var liveSince: ContinuousClock.Instant?
            let reason: String
            do {
                for try await event in source.events() {
                    if case .snapshot = event, liveSince == nil { liveSince = clock.now }
                    apply(event)
                }
                reason = "callboard stopped watching"
            } catch let error as CallboardError where error.isTerminal {
                state = .failed(error.localizedDescription)
                return
            } catch {
                reason = error.localizedDescription
            }
            if Task.isCancelled { return }
            attempt = Self.nextAttempt(attempt, upFor: liveSince.map { clock.now - $0 })
            state = .reconnecting(reason)
            do {
                try await Task.sleep(for: backoff(attempt))
            } catch {
                return
            }
            attempt += 1
        }
    }

    public func select(_ conversationId: String?) async {
        generation += 1
        let token = generation
        loadedLimit = threadLimit
        selectedId = conversationId
        guard let conversationId else {
            thread = .empty
            return
        }
        thread = ThreadState(messages: [], more: false, loading: true, error: nil)
        do {
            let page = try await reader.history(conversationId: conversationId, before: nil, limit: Self.pageSize)
            guard token == generation else { return }
            thread = Self.trimmed(Self.merging(page, into: thread), limit: loadedLimit)
            thread.loading = false
            if isViewing { markSelectedViewed() }
        } catch {
            guard token == generation else { return }
            thread.loading = false
            thread.more = true
            thread.error = error.localizedDescription
        }
    }

    public func loadOlder() async {
        guard let selectedId, thread.more, !thread.loading, let first = thread.messages.first else { return }
        let token = generation
        let epoch = pagingEpoch
        thread.loading = true
        thread.error = nil
        do {
            let page = try await reader.history(conversationId: selectedId, before: first.seq, limit: Self.pageSize)
            guard token == generation, epoch == pagingEpoch else { return }
            thread.messages = Self.union(page.messages, thread.messages)
            thread.more = page.more
            loadedLimit = max(loadedLimit, thread.messages.count)
            thread.loading = false
        } catch {
            guard token == generation, epoch == pagingEpoch else { return }
            thread.loading = false
            thread.error = error.localizedDescription
        }
    }

    private func apply(_ event: WatchEvent) {
        switch event {
        case let .snapshot(snapshot):
            apply(snapshot)
        case let .messages(batch):
            apply(batch)
        }
    }

    private func apply(_ snapshot: Snapshot) {
        let storeChanged = store != snapshot.store
        store = snapshot.store
        conversations = snapshot.conversations
        tracker.begin(store: snapshot.store, snapshot: snapshot.conversations)
        state = .live
        refreshCounts()
        guard let selectedId else { return }
        guard conversations.contains(where: { $0.id == selectedId }) else {
            clearSelection()
            return
        }
        if storeChanged {
            generation += 1
            thread = .empty
        }
        if isViewing { markSelectedViewed() }
        reload?.cancel()
        reload = Task { await reloadThread(selectedId) }
    }

    private func apply(_ batch: MessageBatch) {
        conversations = Self.upserting(batch.conversations, into: conversations)
        if let selectedId {
            let lastSeq = thread.messages.last?.seq ?? Int64.min
            let appended = batch.messages.filter { $0.conversationId == selectedId && $0.seq > lastSeq }
            if !appended.isEmpty {
                thread.messages += appended
                if !thread.loading { thread = Self.trimmed(thread, limit: loadedLimit) }
            }
            if isViewing, batch.conversations.contains(where: { $0.id == selectedId }) { markSelectedViewed() }
        }
        refreshCounts()
    }

    private func reloadThread(_ conversationId: String) async {
        let token = generation
        do {
            let page = try await reader.history(conversationId: conversationId, before: nil, limit: Self.pageSize)
            guard token == generation else { return }
            if Self.replaces(thread, with: page) {
                pagingEpoch += 1
                thread.loading = false
            }
            thread = Self.merging(page, into: thread)
            if !thread.loading { thread = Self.trimmed(thread, limit: loadedLimit) }
            thread.error = nil
        } catch {
            guard token == generation, !Task.isCancelled else { return }
            thread.error = error.localizedDescription
        }
    }

    private func clearSelection() {
        generation += 1
        selectedId = nil
        thread = .empty
    }

    private func markSelectedViewed() {
        guard let selectedId, let summary = conversations.first(where: { $0.id == selectedId }) else { return }
        tracker.markViewed(summary)
        refreshCounts()
    }

    private func refreshCounts() {
        newCounts = Dictionary(conversations.map { ($0.id, tracker.newCount(for: $0)) }, uniquingKeysWith: { $1 })
    }

    static func upserting(
        _ updates: [ConversationSummary],
        into current: [ConversationSummary]
    ) -> [ConversationSummary] {
        let updated = Dictionary(updates.map { ($0.id, $0) }, uniquingKeysWith: { $1 })
        let known = Set(current.map(\.id))
        let added = updated.values.filter { !known.contains($0.id) }.sorted { $0.id < $1.id }
        return current.map { updated[$0.id] ?? $0 } + added
    }

    static func union(_ older: [ChatMessage], _ newer: [ChatMessage]) -> [ChatMessage] {
        Dictionary((older + newer).map { ($0.seq, $0) }, uniquingKeysWith: { $1 }).values.sorted { $0.seq < $1.seq }
    }

    static func merging(_ page: HistoryPage, into thread: ThreadState) -> ThreadState {
        var merged = thread
        guard replaces(thread, with: page) else {
            merged.messages = union(thread.messages, page.messages)
            merged.more = reachesFurther(thread, than: page) ? thread.more : page.more
            return merged
        }
        merged.messages = page.messages
        merged.more = page.more
        return merged
    }

    private static func replaces(_ thread: ThreadState, with page: HistoryPage) -> Bool {
        guard let last = thread.messages.last, let pageFirst = page.messages.first else { return false }
        return page.more && pageFirst.seq > last.seq
    }

    private static func reachesFurther(_ thread: ThreadState, than page: HistoryPage) -> Bool {
        thread.messages.first.map { $0.seq < (page.messages.first?.seq ?? Int64.max) } ?? false
    }

    static func trimmed(_ thread: ThreadState, limit: Int) -> ThreadState {
        guard thread.messages.count > limit else { return thread }
        var trimmed = thread
        trimmed.messages = Array(thread.messages.suffix(limit))
        trimmed.more = true
        return trimmed
    }
}
