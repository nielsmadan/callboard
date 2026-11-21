import CallboardKit
import Foundation
import Synchronization

final class Gate: Sendable {
    private let state = Mutex<(open: Bool, waiters: [CheckedContinuation<Void, Never>])>((false, []))

    func open() {
        let waiters = state.withLock { state in
            state.open = true
            defer { state.waiters = [] }
            return state.waiters
        }
        waiters.forEach { $0.resume() }
    }

    func wait() async {
        await withCheckedContinuation { continuation in
            let resumeNow = state.withLock { state in
                if !state.open { state.waiters.append(continuation) }
                return state.open
            }
            if resumeNow { continuation.resume() }
        }
    }
}

struct HistoryRequest: Sendable, Equatable {
    let conversationId: String
    let before: Int64?
}

actor FakeReader: CallboardReading {
    typealias Handler = @Sendable (HistoryRequest) async throws -> HistoryPage

    private let handler: Handler
    private(set) var requests: [HistoryRequest] = []

    init(_ handler: @escaping Handler) {
        self.handler = handler
    }

    init(pages: [String: HistoryPage]) {
        self.init { request in
            guard let page = pages[request.conversationId] else {
                throw CallboardError.commandFailed(
                    command: "admin history", exitCode: 3, code: "conversation_not_found",
                    message: request.conversationId
                )
            }
            return page
        }
    }

    func history(conversationId: String, before: Int64?, limit _: Int) async throws -> HistoryPage {
        let request = HistoryRequest(conversationId: conversationId, before: before)
        requests.append(request)
        return try await handler(request)
    }
}

final class FakeSource: EventSource {
    typealias Feed = AsyncThrowingStream<WatchEvent, Error>.Continuation

    private let feeds = Mutex<[Feed]>([])

    var calls: Int {
        feeds.withLock(\.count)
    }

    func events() -> AsyncThrowingStream<WatchEvent, Error> {
        let (stream, continuation) = AsyncThrowingStream.makeStream(of: WatchEvent.self, throwing: Error.self)
        feeds.withLock { $0.append(continuation) }
        return stream
    }

    @MainActor func feed(_ index: Int) async -> Feed? {
        let opened = await eventually { self.calls > index }
        return opened ? feeds.withLock { $0[index] } : nil
    }
}

@MainActor func eventually(within limit: Duration = .seconds(5), _ condition: () -> Bool) async -> Bool {
    let deadline = ContinuousClock.now + limit
    while !condition() {
        guard ContinuousClock.now < deadline else { return false }
        await Task.yield()
    }
    return true
}

@MainActor final class RecordingTracker: ViewTracker {
    private let inner: any ViewTracker
    private(set) var marked: [String] = []

    init(_ inner: any ViewTracker) {
        self.inner = inner
    }

    func begin(store: String, snapshot: [ConversationSummary]) {
        inner.begin(store: store, snapshot: snapshot)
    }

    func newCount(for conversation: ConversationSummary) -> Int {
        inner.newCount(for: conversation)
    }

    func markViewed(_ conversation: ConversationSummary) {
        marked.append(conversation.id)
        inner.markViewed(conversation)
    }
}
