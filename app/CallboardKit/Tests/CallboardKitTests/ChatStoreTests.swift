import CallboardKit
import Foundation
import Synchronization
import Testing

private enum HarnessError: Error {
    case noFeed(Int)
}

@MainActor
private final class Harness {
    let source = FakeSource()
    let reader: FakeReader
    let store: ChatStore
    private let suiteName = "callboard-chatstore-\(UUID().uuidString)"
    private var task: Task<Void, Never>?

    let tracker: RecordingTracker

    init(reader: FakeReader = FakeReader(pages: [:]), threadLimit: Int = 1000) {
        self.reader = reader
        let defaults = UserDefaults(suiteName: suiteName) ?? .standard
        tracker = RecordingTracker(LocalViewTracker(defaults: defaults))
        store = ChatStore(
            reader: reader,
            source: source,
            tracker: tracker,
            backoff: { _ in .zero },
            threadLimit: threadLimit
        )
    }

    func start() async throws -> FakeSource.Feed {
        task = Task { [store] in await store.run() }
        return try await feed(0)
    }

    func feed(_ index: Int) async throws -> FakeSource.Feed {
        guard let feed = await source.feed(index) else {
            await stop()
            throw HarnessError.noFeed(index)
        }
        return feed
    }

    func finished() async {
        await task?.value
    }

    func stop() async {
        task?.cancel()
        await task?.value
        UserDefaults.standard.removePersistentDomain(forName: suiteName)
    }

    func send(_ event: WatchEvent, on feed: FakeSource.Feed, until condition: () -> Bool) async -> Bool {
        feed.yield(event)
        return await eventually(condition)
    }
}

@Suite("ChatStore", .timeLimit(.minutes(1)))
@MainActor
struct ChatStoreTests {
    private let ops = "group:ops"
    private let dm = "dm:enki:nanna"

    private var opening: WatchEvent {
        Make.snapshot([Make.conversation(ops, name: "ops", seqs: [1, 2]), Make.conversation(dm, seqs: [3])])
    }

    private func opsPage(_ seqs: [Int64], more: Bool = false) -> HistoryPage {
        Make.page(Make.conversation(ops, seqs: seqs), seqs.map { Make.message($0, in: ops) }, more: more)
    }

    private func opsBatch(_ added: [Int64], total: [Int64]) -> WatchEvent {
        Make.batch(added.map { Make.message($0, in: ops) }, touching: [Make.conversation(ops, seqs: total)])
    }

    @Test func firstLaunchCountsNothingAsNew() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        #expect(harness.store.conversations.map(\.id) == [ops, dm])
        #expect(harness.store.store == Make.store)
        #expect(harness.store.totalNew == 0)
        await harness.stop()
    }

    @Test func batchRaisesCountToTheServerValue() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        feed.yield(opening)
        #expect(await harness.send(opsBatch([4, 5], total: [1, 2, 4, 5]), on: feed) {
            harness.store.newCount(for: ops) == 2
        })
        #expect(harness.store.totalNew == 2)
        #expect(harness.store.conversations.first?.last?.seq == 5)
        await harness.stop()
    }

    @Test func replayedBatchKeepsTheServerCount() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        feed.yield(opening)
        feed.yield(opsBatch([4], total: [1, 2, 4]))
        feed.yield(opsBatch([4], total: [1, 2, 4]))
        let sentinel = Make.batch([Make.message(5, in: dm)], touching: [Make.conversation(dm, seqs: [3, 5])])
        #expect(await harness.send(sentinel, on: feed) { harness.store.newCount(for: dm) == 1 })
        #expect(harness.store.newCount(for: ops) == 1)
        #expect(harness.store.totalNew == 2)
        await harness.stop()
    }

    @Test func viewingTheSelectionKeepsItSeenWhileTheThreadAppends() async throws {
        let harness = Harness(reader: FakeReader(pages: [ops: opsPage([1, 2])]))
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        harness.store.isViewing = true
        await harness.store.select(ops)
        #expect(await harness.send(opsBatch([3], total: [1, 2, 3]), on: feed) {
            harness.store.thread.messages.map(\.seq) == [1, 2, 3]
        })
        #expect(harness.store.conversations.first?.messages == 3)
        #expect(harness.store.newCount(for: ops) == 0)
        await harness.stop()
    }

    @Test func notViewingRaisesTheCountUntilViewingResumes() async throws {
        let harness = Harness(reader: FakeReader(pages: [ops: opsPage([1, 2])]))
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        #expect(await harness.send(opsBatch([3], total: [1, 2, 3]), on: feed) {
            harness.store.thread.messages.map(\.seq) == [1, 2, 3]
        })
        #expect(harness.store.newCount(for: ops) == 1)
        harness.store.isViewing = true
        #expect(harness.store.newCount(for: ops) == 0)
        #expect(harness.store.totalNew == 0)
        await harness.stop()
    }

    @Test func recreatedConversationCountsAllItsMessages() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        feed.yield(opening)
        let recreated = Make.snapshot([Make.conversation(ops, seqs: [7, 8, 9]), Make.conversation(dm, seqs: [3])])
        #expect(await harness.send(recreated, on: feed) { harness.store.newCount(for: ops) == 3 })
        await harness.stop()
    }

    @Test func eachStoreKeepsItsOwnMarksAndBaseline() async throws {
        let other = "/stores/demo/callboard.sqlite"
        let harness = Harness()
        let feed = try await harness.start()
        feed.yield(opening)
        #expect(await harness.send(opsBatch([4], total: [1, 2, 4]), on: feed) {
            harness.store.newCount(for: ops) == 1
        })
        let demo = Make.snapshot([Make.conversation(ops, seqs: [1, 2, 3, 4, 5])], store: other)
        #expect(await harness.send(demo, on: feed) { harness.store.store == other })
        #expect(harness.store.totalNew == 0)
        let back = Make.snapshot([Make.conversation(ops, seqs: [1, 2, 4]), Make.conversation(dm, seqs: [3])])
        #expect(await harness.send(back, on: feed) { harness.store.store == Make.store })
        #expect(harness.store.newCount(for: ops) == 1)
        await harness.stop()
    }

    @Test func selectionDisappearingFromASnapshotClearsIt() async throws {
        let harness = Harness(reader: FakeReader(pages: [ops: opsPage([1, 2])]))
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        #expect(harness.store.selectedId == ops)
        #expect(await harness.send(Make.snapshot([Make.conversation(dm, seqs: [3])]), on: feed) {
            harness.store.selectedId == nil
        })
        #expect(harness.store.thread.messages.isEmpty)
        await harness.stop()
    }

    @Test func snapshotReloadsTheSelectedThread() async throws {
        let calls = Mutex(0)
        let harness = Harness(reader: FakeReader { [ops] _ in
            let seqs: [Int64] = calls.withLock { count in
                count += 1
                return count == 1 ? [1, 2] : [1, 2, 3]
            }
            return Make.page(Make.conversation(ops, seqs: seqs), seqs.map { Make.message($0, in: ops) })
        })
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        #expect(harness.store.thread.messages.map(\.seq) == [1, 2])
        #expect(await harness.send(opening, on: feed) { harness.store.thread.messages.map(\.seq) == [1, 2, 3] })
        await harness.stop()
    }

    @Test func streamErrorReconnectsAndTheNextSnapshotGoesLive() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        feed.finish(throwing: CallboardError.streamEnded(exitCode: 1, standardError: "store vanished"))
        let next = try await harness.feed(1)
        if case let .reconnecting(reason) = harness.store.state {
            #expect(reason.contains("store vanished"))
        } else {
            Issue.record("expected reconnecting, got \(harness.store.state)")
        }
        #expect(await harness.send(opening, on: next) { harness.store.state == .live })
        await harness.stop()
    }

    @Test func terminalErrorFailsWithoutRetrying() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        feed.finish(throwing: CallboardError.executableNotFound(searched: ["/opt/callboard"]))
        await harness.finished()
        if case let .failed(reason) = harness.store.state {
            #expect(reason.contains("/opt/callboard"))
        } else {
            Issue.record("expected failed, got \(harness.store.state)")
        }
        #expect(harness.source.calls == 1)
        await harness.stop()
    }

    @Test func staleSelectResponseIsIgnored() async throws {
        let arrived = Gate()
        let release = Gate()
        let first = opsPage([1, 2])
        let second = Make.page(Make.conversation(dm, seqs: [3]), [Make.message(3, in: dm)])
        let harness = Harness(reader: FakeReader { [ops] request in
            guard request.conversationId == ops else { return second }
            arrived.open()
            await release.wait()
            return first
        })
        let pending = Task { await harness.store.select(ops) }
        await arrived.wait()
        await harness.store.select(dm)
        release.open()
        await pending.value
        #expect(harness.store.selectedId == dm)
        #expect(harness.store.thread.messages.map(\.id) == ["cb_3"])
        await harness.stop()
    }

    @Test func historyMergesWithMessagesAppendedDuringTheLoad() async throws {
        let arrived = Gate()
        let release = Gate()
        let page = opsPage([1, 2, 3])
        let harness = Harness(reader: FakeReader { _ in
            arrived.open()
            await release.wait()
            return page
        })
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        let pending = Task { await harness.store.select(ops) }
        await arrived.wait()
        #expect(await harness.send(opsBatch([3], total: [1, 2, 3]), on: feed) {
            harness.store.thread.messages.map(\.seq) == [3]
        })
        release.open()
        await pending.value
        #expect(harness.store.thread.messages.map(\.seq) == [1, 2, 3])
        #expect(harness.store.thread.loading == false)
        await harness.stop()
    }

    @Test func loadOlderPrependsUntilNothingMoreRemains() async throws {
        let harness = Harness(reader: FakeReader { [ops] request in
            request.before == nil
                ? Make.page(
                    Make.conversation(ops, seqs: [1, 2, 3, 4]),
                    [3, 4].map { Make.message($0, in: ops) },
                    more: true
                )
                : Make.page(Make.conversation(ops, seqs: [1, 2, 3, 4]), [1, 2].map { Make.message($0, in: ops) })
        })
        await harness.store.select(ops)
        #expect(harness.store.thread.more)
        await harness.store.loadOlder()
        #expect(harness.store.thread.messages.map(\.seq) == [1, 2, 3, 4])
        #expect(harness.store.thread.more == false)
        await harness.store.loadOlder()
        #expect(await harness.reader.requests.map(\.before) == [nil, 3])
        await harness.stop()
    }

    @Test func liveThreadTrimsTheOldestAtTheLimit() async throws {
        let harness = Harness(reader: FakeReader(pages: [ops: opsPage([1, 2])]), threadLimit: 3)
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        #expect(await harness.send(opsBatch([3, 4], total: [1, 2, 3, 4]), on: feed) {
            harness.store.thread.messages.map(\.seq) == [2, 3, 4]
        })
        #expect(harness.store.thread.more)
        await harness.stop()
    }

    @Test func historyFailureIsReportedOnTheThread() async throws {
        let harness = Harness()
        await harness.store.select(ops)
        #expect(harness.store.thread.error?.contains(ops) == true)
        #expect(harness.store.thread.loading == false)
        await harness.store.select(nil)
        #expect(harness.store.selectedId == nil)
        await harness.stop()
    }

    @Test func sectionsArrangeTheStoreConversations() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        let event = Make.snapshot([
            Make.conversation(ops, name: "ops", seqs: [1, 2]),
            Make.conversation(dm, seqs: [3]),
            Make.conversation("mail:1", seqs: [4])
        ])
        #expect(await harness.send(event, on: feed) { harness.store.state == .live })
        #expect(harness.store.chatConversations.map(\.id) == [ops, dm])
        #expect(harness.store.sections(mode: .recent).flatMap(\.rows).map(\.id) == [dm, ops])
        await harness.stop()
    }

    @Test func emptyConversationsStillBaselineSoLaterMessagesCount() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        let empty = Make.snapshot([Make.conversation(ops, name: "ops")])
        #expect(await harness.send(empty, on: feed) { harness.store.state == .live })
        #expect(await harness.send(opsBatch([1, 2], total: [1, 2]), on: feed) { harness.store.newCount(for: ops) == 2 })
        #expect(harness.store.totalNew == 2)
        await harness.stop()
    }

    @Test func reconnectPageThatSkipsTheThreadReplacesIt() async throws {
        let calls = Mutex(0)
        let harness = Harness(reader: FakeReader { [ops] _ in
            let first = calls.withLock { count in
                count += 1
                return count == 1
            }
            return first
                ? Make.page(Make.conversation(ops, seqs: [1, 2, 3]), [1, 2, 3].map { Make.message($0, in: ops) })
                : Make.page(
                    Make.conversation(ops, seqs: Array(1 ... 61)),
                    [60, 61].map { Make.message($0, in: ops) },
                    more: true
                )
        })
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        #expect(harness.store.thread.messages.map(\.seq) == [1, 2, 3])
        #expect(await harness.send(opening, on: feed) { harness.store.thread.messages.map(\.seq) == [60, 61] })
        #expect(harness.store.thread.more)
        await harness.stop()
    }

    private func pagedReader() -> FakeReader {
        FakeReader { [ops] request in
            request.before == nil
                ? Make.page(
                    Make.conversation(ops, seqs: Array(1 ... 5)),
                    [3, 4, 5].map { Make.message($0, in: ops) },
                    more: true
                )
                : Make.page(Make.conversation(ops, seqs: Array(1 ... 5)), [1, 2].map { Make.message($0, in: ops) })
        }
    }

    @Test func liveAppendKeepsThePagesLoadedOlderUntilTheNextSelect() async throws {
        let harness = Harness(reader: pagedReader(), threadLimit: 3)
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        await harness.store.loadOlder()
        #expect(harness.store.thread.messages.map(\.seq) == [1, 2, 3, 4, 5])
        #expect(await harness.send(opsBatch([6], total: Array(1 ... 6)), on: feed) {
            harness.store.thread.messages.map(\.seq) == [2, 3, 4, 5, 6]
        })
        await harness.store.select(ops)
        #expect(await harness.send(opsBatch([6], total: Array(1 ... 6)), on: feed) {
            harness.store.thread.messages.map(\.seq) == [4, 5, 6]
        })
        await harness.stop()
    }

    @Test func liveAppendDuringLoadOlderDoesNotTrimAGapIntoTheThread() async throws {
        let arrived = Gate()
        let release = Gate()
        let paged = pagedReader()
        let harness = Harness(reader: FakeReader { [ops] request in
            if request.before != nil {
                arrived.open()
                await release.wait()
            }
            return try await paged.history(conversationId: ops, before: request.before, limit: 50)
        }, threadLimit: 3)
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        let pending = Task { await harness.store.loadOlder() }
        await arrived.wait()
        #expect(await harness.send(opsBatch([6], total: Array(1 ... 6)), on: feed) {
            harness.store.thread.messages.map(\.seq) == [3, 4, 5, 6]
        })
        release.open()
        await pending.value
        #expect(harness.store.thread.messages.map(\.seq) == [1, 2, 3, 4, 5, 6])
        await harness.stop()
    }

    @Test func reloadReplacingTheThreadDuringLoadOlderDropsTheOlderPage() async throws {
        let arrived = Gate()
        let release = Gate()
        let latestCalls = Mutex(0)
        let harness = Harness(reader: FakeReader { [ops] request in
            guard request.before == nil else {
                arrived.open()
                await release.wait()
                return Make.page(Make.conversation(ops, seqs: [1, 2]), [1, 2].map { Make.message($0, in: ops) })
            }
            let call = latestCalls.withLock { calls in
                calls += 1
                return calls
            }
            let seqs: [Int64] = call == 1 ? [3, 4, 5] : [60, 61]
            return Make.page(
                Make.conversation(ops, seqs: seqs), seqs.map { Make.message($0, in: ops) }, more: true
            )
        })
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        let pending = Task { await harness.store.loadOlder() }
        await arrived.wait()
        #expect(await harness.send(opening, on: feed) { harness.store.thread.messages.map(\.seq) == [60, 61] })
        release.open()
        await pending.value
        #expect(harness.store.thread.messages.map(\.seq) == [60, 61])
        #expect(harness.store.thread.more)
        #expect(harness.store.thread.loading == false)
        await harness.store.loadOlder()
        #expect(await harness.reader.requests.map(\.before) == [nil, 3, nil, 60])
        await harness.stop()
    }

    @Test func failedSelectStillOffersOlderMessagesOnceAppendsArrive() async throws {
        let harness = Harness()
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        #expect(await harness.send(opsBatch([3], total: [1, 2, 3]), on: feed) {
            harness.store.thread.messages.map(\.seq) == [3]
        })
        #expect(harness.store.thread.more)
        await harness.stop()
    }

    private func switchedStoreReader(firstGate: Gate? = nil, arrived: Gate? = nil) -> FakeReader {
        let calls = Mutex(0)
        return FakeReader { [ops] _ in
            let call = calls.withLock { count in
                count += 1
                return count
            }
            if call == 1, let firstGate {
                arrived?.open()
                await firstGate.wait()
            }
            let seqs: [Int64] = call == 1 ? [1, 2] : [10, 11]
            return Make.page(Make.conversation(ops, seqs: seqs), seqs.map { Make.message($0, in: ops) })
        }
    }

    @Test func storeChangeClearsTheSelectedThreadBeforeReloading() async throws {
        let other = "/stores/demo/callboard.sqlite"
        let harness = Harness(reader: switchedStoreReader())
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        #expect(harness.store.thread.messages.map(\.seq) == [1, 2])
        let demo = Make.snapshot([Make.conversation(ops, seqs: [10, 11])], store: other)
        #expect(await harness.send(demo, on: feed) { harness.store.thread.messages.map(\.seq) == [10, 11] })
        await harness.stop()
    }

    @Test func historyInFlightAcrossAStoreChangeIsIgnored() async throws {
        let other = "/stores/demo/callboard.sqlite"
        let arrived = Gate()
        let release = Gate()
        let harness = Harness(reader: switchedStoreReader(firstGate: release, arrived: arrived))
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        let pending = Task { await harness.store.select(ops) }
        await arrived.wait()
        let demo = Make.snapshot([Make.conversation(ops, seqs: [10, 11])], store: other)
        #expect(await harness.send(demo, on: feed) { harness.store.thread.messages.map(\.seq) == [10, 11] })
        release.open()
        await pending.value
        #expect(harness.store.thread.messages.map(\.seq) == [10, 11])
        await harness.stop()
    }

    @Test func snapshotWhileViewingMarksTheSelectionViewed() async throws {
        let harness = Harness(reader: FakeReader(pages: [ops: opsPage([1, 2])]))
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        harness.store.isViewing = true
        await harness.store.select(ops)
        let grown = Make.snapshot([Make.conversation(ops, seqs: [1, 2, 3, 4, 5]), Make.conversation(dm, seqs: [3])])
        #expect(await harness.send(grown, on: feed) { harness.store.conversations.first?.messages == 5 })
        #expect(harness.store.newCount(for: ops) == 0)
        await harness.stop()
    }

    @Test func batchesForOtherConversationsDoNotRewriteTheViewMarks() async throws {
        let harness = Harness(reader: FakeReader(pages: [ops: opsPage([1, 2])]))
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        harness.store.isViewing = true
        await harness.store.select(ops)
        let marked = harness.tracker.marked
        let other = Make.batch([Make.message(5, in: dm)], touching: [Make.conversation(dm, seqs: [3, 5])])
        #expect(await harness.send(other, on: feed) { harness.store.newCount(for: dm) == 1 })
        #expect(harness.tracker.marked == marked)
        #expect(await harness.send(opsBatch([6], total: [1, 2, 6]), on: feed) {
            harness.store.thread.messages.map(\.seq) == [1, 2, 6]
        })
        #expect(harness.tracker.marked == marked + [ops])
        await harness.stop()
    }

    @Test func slowHistoryReloadDoesNotStallTheFeed() async throws {
        let release = Gate()
        let calls = Mutex(0)
        let harness = Harness(reader: FakeReader { [ops] _ in
            let call = calls.withLock { count in
                count += 1
                return count
            }
            if call > 1 { await release.wait() }
            return Make.page(Make.conversation(ops, seqs: [1, 2]), [1, 2].map { Make.message($0, in: ops) })
        })
        let feed = try await harness.start()
        #expect(await harness.send(opening, on: feed) { harness.store.state == .live })
        await harness.store.select(ops)
        feed.yield(opening)
        let other = Make.batch([Make.message(5, in: dm)], touching: [Make.conversation(dm, seqs: [3, 5])])
        #expect(await harness.send(other, on: feed) { harness.store.newCount(for: dm) == 1 })
        release.open()
        await harness.stop()
    }

    @Test func attemptResetsOnlyAfterAStreamStayedUpLongEnough() {
        let cases: [(Int, Duration?, Int)] = [
            (3, nil, 3), (3, .seconds(29), 3), (3, .seconds(30), 0), (3, .seconds(300), 0)
        ]
        #expect(cases.map { ChatStore.nextAttempt($0.0, upFor: $0.1) } == cases.map(\.2))
    }

    @Test func defaultBackoffDoublesUpToThirtySeconds() {
        #expect((0 ..< 7).map(ChatStore.defaultBackoff) == [1, 2, 4, 8, 16, 30, 30].map { .seconds($0) })
    }
}
