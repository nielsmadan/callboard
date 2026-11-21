import CallboardKit
import Foundation
import Testing

@Suite("CallboardWatch", .timeLimit(.minutes(1)))
struct CallboardWatchTests {
    private static let serveThenWait = "cat \"$DIR/lines\"\nwhile read -r _; do :; done"
    private static let serveThenExit = "cat \"$DIR/lines\""

    private struct Outcome {
        var events: [WatchEvent] = []
        var error: (any Error)?

        var failure: CallboardError? {
            error as? CallboardError
        }

        var cursors: [Int64] {
            events.map { event in
                switch event {
                case let .snapshot(snapshot): snapshot.cursor
                case let .messages(batch): batch.cursor
                }
            }
        }
    }

    private func drain(
        _ stream: AsyncThrowingStream<WatchEvent, Error>,
        onEvent: @Sendable () -> Void = {}
    ) async -> Outcome {
        var outcome = Outcome()
        do {
            for try await event in stream {
                outcome.events.append(event)
                onEvent()
            }
        } catch {
            outcome.error = error
        }
        return outcome
    }

    private func first(_ count: Int, of stream: AsyncThrowingStream<WatchEvent, Error>) async throws -> [WatchEvent] {
        var events: [WatchEvent] = []
        for try await event in stream {
            events.append(event)
            if events.count == count { break }
        }
        return events
    }

    @Test func snapshotThenMessagesArriveInOrder() async throws {
        let lines = try [WatchLine.snapshot(), WatchLine.messages()]
        try await WatchStub.with(lines: lines, script: Self.serveThenWait) { stub in
            let source: any EventSource = CallboardWatch(command: stub.command)
            let events = try await first(2, of: source.events())
            guard events.count == 2, case let .snapshot(snapshot) = events[0], case let .messages(batch) = events[1]
            else {
                Issue.record("expected a snapshot then messages, got \(events)")
                return
            }
            #expect(snapshot.conversations.map(\.id) == ["group:ops", "dm:enki:nanna"])
            #expect(batch.messages.map(\.seq) == [2, 3])
            #expect(batch.conversations.map(\.id) == ["group:ops"])
        }
    }

    @Test func watchRunsTheAdminCommandWithTheCommandEnvironment() async throws {
        let script = "sed \"s|/home/u/.local/share/callboard/callboard.sqlite|$STUB_MARK|\" \"$DIR/lines\"\n"
            + "while read -r _; do :; done"
        let lines = try [WatchLine.snapshot()]
        try await WatchStub.with(lines: lines, script: script, environment: ["STUB_MARK": "/marked/store"]) { stub in
            let events = try await first(1, of: CallboardWatch(command: stub.command, interval: 0.5).events())
            guard case let .snapshot(snapshot) = events.first else {
                Issue.record("expected a snapshot, got \(events)")
                return
            }
            #expect(snapshot.store == "/marked/store")
            #expect(stub.arguments == ["admin", "watch", "--json", "--interval", "0.5"])
        }
    }

    @Test func aLineSplitAcrossTwoWritesDecodes() async throws {
        let script = "head -c 100 \"$DIR/lines\"\nsleep 0.3\ntail -c +101 \"$DIR/lines\"\nwhile read -r _; do :; done"
        try await WatchStub.with(lines: [WatchLine.snapshot()], script: script) { stub in
            let events = try await first(1, of: CallboardWatch(command: stub.command).events())
            #expect(Outcome(events: events).cursors == [3])
        }
    }

    @Test func everyLineArrivesWhenTheChildExitsRightAfterWriting() async throws {
        let lines = try (1 ... 2000).map { try WatchLine.empty(cursor: $0) }
        try await WatchStub.with(lines: lines, script: Self.serveThenExit) { stub in
            for _ in 1 ... 20 {
                let outcome = await drain(CallboardWatch(command: stub.command).events())
                #expect(outcome.cursors == Array(1 ... 2000))
                #expect(outcome.failure == .streamEnded(exitCode: 0, standardError: ""))
            }
        }
    }

    @Test func aFailingExitEndsTheStreamWithTheStderrTail() async throws {
        try await WatchStub.with(script: "echo 'store is busy' >&2\nexit 1") { stub in
            let outcome = await drain(CallboardWatch(command: stub.command).events())
            #expect(outcome.failure == .streamEnded(exitCode: 1, standardError: "store is busy"))
        }
    }

    @Test func anErrorEnvelopeBecomesCommandFailed() async throws {
        let error = try WatchLine.envelope([
            "status": "error",
            "error": ["code": "store_busy", "message": "the store stayed locked for 30 s"]
        ])
        let lines = try [WatchLine.snapshot(), error]
        try await WatchStub.with(lines: lines, script: Self.serveThenExit + "\nexit 1") { stub in
            let outcome = await drain(CallboardWatch(command: stub.command).events())
            #expect(outcome.cursors == [3])
            #expect(outcome.failure == .commandFailed(
                command: "admin watch",
                exitCode: 1,
                code: "store_busy",
                message: "the store stayed locked for 30 s"
            ))
        }
    }

    @Test func anUnrequestedCleanExitStillEndsTheStream() async throws {
        try await WatchStub.with(lines: [WatchLine.snapshot()], script: Self.serveThenExit) { stub in
            let outcome = await drain(CallboardWatch(command: stub.command).events())
            #expect(outcome.cursors == [3])
            #expect(outcome.failure == .streamEnded(exitCode: 0, standardError: ""))
        }
    }

    @Test func aDescendantHoldingThePipesDoesNotKeepTheStreamOpen() async throws {
        let script = Self.serveThenExit + "\nsleep 8 &\necho $! >> \"$DIR/pid\""
        try await WatchStub.with(lines: [WatchLine.snapshot()], script: script) { stub in
            let clock = ContinuousClock()
            var outcome = Outcome()
            let elapsed = await clock.measure { outcome = await drain(CallboardWatch(command: stub.command).events()) }
            #expect(outcome.cursors == [3])
            #expect(outcome.failure == .streamEnded(exitCode: 0, standardError: ""))
            #expect(elapsed < .seconds(4))
        }
    }

    @Test func aDescendantWritingContinuouslyStillEndsTheStream() async throws {
        let script = Self.serveThenExit
            + "\n(while :; do echo noise >&2; sleep 0.3; done) &\necho $! >> \"$DIR/pid\""
        try await WatchStub.with(lines: [WatchLine.snapshot()], script: script) { stub in
            let clock = ContinuousClock()
            var outcome = Outcome()
            let elapsed = await clock.measure { outcome = await drain(CallboardWatch(command: stub.command).events()) }
            #expect(outcome.cursors == [3])
            guard case .streamEnded(exitCode: 0, _) = outcome.failure else {
                Issue.record("expected streamEnded, got \(String(describing: outcome.error))")
                return
            }
            #expect(elapsed < .seconds(8))
        }
    }

    @Test func anUnknownEventIsSkippedAndTheStreamKeepsGoing() async throws {
        let unknown = try WatchLine.envelope(["event": "presence", "agents": [String]()])
        let lines = try [WatchLine.snapshot(), unknown, WatchLine.messages()]
        try await WatchStub.with(lines: lines, script: Self.serveThenWait) { stub in
            let events = try await first(2, of: CallboardWatch(command: stub.command).events())
            guard events.count == 2, case .snapshot = events[0], case .messages = events[1] else {
                Issue.record("expected a snapshot then messages, got \(events)")
                return
            }
        }
    }

    @Test func theGoldenWatchLinesDecode() async throws {
        let lines = try [WatchLine.golden("admin-watch-snapshot"), WatchLine.golden("admin-watch-messages")]
        try await WatchStub.with(lines: lines, script: Self.serveThenWait) { stub in
            let events = try await first(2, of: CallboardWatch(command: stub.command).events())
            guard events.count == 2, case let .snapshot(snapshot) = events[0], case let .messages(batch) = events[1]
            else {
                Issue.record("expected a snapshot then messages, got \(events)")
                return
            }
            #expect(snapshot.store == "/home/u/.local/share/callboard/callboard.sqlite")
            #expect(snapshot.cursor == 3)
            #expect(snapshot.conversations.map(\.id) == ["group:ops", "dm:enki:nanna"])
            #expect(snapshot.conversations.map(\.firstSeq) == [2, 1])
            #expect(snapshot.conversations[1].last?.preview == "first line\\nsecond line")
            #expect(batch.cursor == 4)
            let reply = try #require(batch.messages.first)
            #expect(batch.messages.count == 1)
            #expect(reply.seq == 4)
            #expect(reply.conversationId == "group:ops")
            #expect(reply.sender == "nanna")
            #expect(reply.body == "lgtm")
            #expect(reply.parentId == "cb_000000000003")
            #expect(reply.bodyTruncated == false)
            #expect(reply.attachments.isEmpty)
            #expect(batch.conversations.map(\.messages) == [3])
            #expect(batch.conversations.first?.last?.id == "cb_000000000004")
        }
    }

    @Test func aLineOverSixteenMegabytesStillDecodes() async throws {
        var conversation = Make.conversation("mail:big")
        conversation["subject"] = String(repeating: "s", count: 17_000_000)
        let line = try WatchLine.envelope([
            "event": "snapshot",
            "store": "s",
            "cursor": 0,
            "conversations": [conversation]
        ])
        try await WatchStub.with(lines: [line], script: Self.serveThenWait) { stub in
            let events = try await first(1, of: CallboardWatch(command: stub.command).events())
            guard case let .snapshot(snapshot) = events.first else {
                Issue.record("expected a snapshot, got \(events)")
                return
            }
            #expect(snapshot.conversations.first?.subject?.count == 17_000_000)
        }
    }

    @Test func anOverlongLineIsMalformed() async throws {
        let script = "head -c 68000000 /dev/zero | tr '\\0' x\nwhile read -r _; do :; done"
        try await WatchStub.with(script: script) { stub in
            let outcome = await drain(CallboardWatch(command: stub.command).events())
            #expect(outcome.failure == .malformedOutput(command: "admin watch", detail: "a line is longer than 64 MB"))
            #expect(stub.status == ["exited"])
        }
    }

    @Test func aLineThatIsNotAnEnvelopeIsMalformed() async throws {
        try await WatchStub.with(lines: ["not json"], script: Self.serveThenWait) { stub in
            let outcome = await drain(CallboardWatch(command: stub.command).events())
            #expect(outcome.failure == .malformedOutput(
                command: "admin watch",
                detail: "a line is not a callboard envelope"
            ))
        }
    }

    @Test func aNewerSchemaIsUnsupported() async throws {
        let line = #"{"schema_version":2,"status":"ok","warnings":[],"event":"snapshot"}"#
        try await WatchStub.with(lines: [line], script: Self.serveThenWait) { stub in
            let outcome = await drain(CallboardWatch(command: stub.command).events())
            #expect(outcome.failure == .unsupportedSchema(2))
        }
    }

    @Test func aMissingExecutableIsNotFound() async {
        let command = CallboardCommand(executable: URL(filePath: "/nonexistent/callboard"))
        let outcome = await drain(CallboardWatch(command: command).events())
        #expect(outcome.failure == .executableNotFound(searched: ["/nonexistent/callboard"]))
    }

    @Test func cancellingClosesTheLifelineAndTheChildExits() async throws {
        let script = "trap 'echo term >> \"$DIR/status\"' TERM\n" + Self.serveThenWait
        try await WatchStub.with(lines: [WatchLine.snapshot()], script: script) { stub in
            let stream = CallboardWatch(command: stub.command).events()
            let (arrived, signal) = AsyncStream<Void>.makeStream()
            let consumer = Task { await drain(stream) { signal.yield() } }
            var waiter = arrived.makeAsyncIterator()
            _ = await waiter.next()
            #expect(stub.isAlive)
            consumer.cancel()
            #expect(await WatchStub.until(.seconds(10)) { stub.status.contains("exited") })
            #expect(stub.status == ["exited"])
            let outcome = await consumer.value
            #expect(outcome.cursors == [3])
            #expect(outcome.error == nil)
        }
    }

    @Test func aChildIgnoringTheLifelineIsKilledAfterTheFallback() async throws {
        let script = "trap 'echo term >> \"$DIR/status\"' TERM\ncat \"$DIR/lines\"\nwhile :; do sleep 0.1; done"
        try await WatchStub.with(lines: [WatchLine.snapshot()], script: script) { stub in
            let stream = CallboardWatch(command: stub.command).events()
            let consumer = Task { await drain(stream) }
            #expect(await WatchStub.until(.seconds(10)) { stub.isAlive })
            let clock = ContinuousClock()
            let start = clock.now
            consumer.cancel()
            #expect(await WatchStub.until(.seconds(10)) { !stub.isAlive })
            #expect(clock.now - start < .seconds(5))
            #expect(stub.status == ["term"])
        }
    }
}
