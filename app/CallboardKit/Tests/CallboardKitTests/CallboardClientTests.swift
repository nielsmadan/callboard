import CallboardKit
import Foundation
import Testing

@Suite("CallboardClient", .timeLimit(.minutes(1)))
struct CallboardClientTests {
    private func serve(_ fixture: String) throws -> String {
        try "cat '\(Fixture.url(fixture).path)'"
    }

    private func failure(of client: CallboardClient) async -> CallboardError? {
        do {
            _ = try await client.history(conversationId: "group:ops", before: nil, limit: 5)
            return nil
        } catch {
            return error as? CallboardError
        }
    }

    @Test func historyRunsTheAdminCommandAndDecodesThePage() async throws {
        let script = try serve("admin-history")
        try await CallboardStub.with(script: script) { stub in
            let page = try await CallboardClient(command: stub.command)
                .history(conversationId: "group:ops", before: nil, limit: 50)
            #expect(page.messages.map(\.seq) == [2, 3])
            #expect(stub.arguments == ["admin", "history", "group:ops", "--limit", "50", "--json"])
        }
    }

    @Test func clientServesHistoryThroughTheReadingProtocol() async throws {
        let script = try serve("admin-history")
        try await CallboardStub.with(script: script) { stub in
            let reader: any CallboardReading = CallboardClient(command: stub.command)
            let page = try await reader.history(conversationId: "group:ops", before: nil, limit: 2)
            #expect(page.conversation.id == "group:ops")
        }
    }

    @Test func historyPassesBeforeWhenGiven() async throws {
        let script = try serve("admin-history")
        try await CallboardStub.with(script: script) { stub in
            _ = try await CallboardClient(command: stub.command)
                .history(conversationId: "dm:a:b", before: 42, limit: 7)
            #expect(stub.arguments == ["admin", "history", "dm:a:b", "--limit", "7", "--before", "42", "--json"])
        }
    }

    @Test func commandEnvironmentReachesTheChild() async throws {
        let fixture = try Fixture.url("admin-history").path
        let script = "sed \"s|/home/u/.local/share/callboard/callboard.sqlite|$STUB_MARK|\" '\(fixture)'"
        try await CallboardStub.with(script: script, environment: ["STUB_MARK": "/marked/store"]) { stub in
            let page = try await CallboardClient(command: stub.command)
                .history(conversationId: "group:ops", before: nil, limit: 5)
            #expect(page.store == "/marked/store")
        }
    }

    @Test func errorEnvelopeBecomesCommandFailedWithItsCode() async throws {
        let envelope = #"{"schema_version":1,"status":"error","warnings":[],"error":{"code":"conversation_not_found","message":"no such conversation"}}"#
        try await CallboardStub.with(script: "echo '\(envelope)'\nexit 3") { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            #expect(error == .commandFailed(
                command: "admin history",
                exitCode: 3,
                code: "conversation_not_found",
                message: "no such conversation"
            ))
            #expect(error?.isTerminal == false)
        }
    }

    @Test func argparseUsageFailureIsTerminal() async throws {
        let script = "echo 'usage: callboard admin [-h]' >&2\necho 'callboard: invalid choice: history' >&2\nexit 2"
        try await CallboardStub.with(script: script) { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            #expect(error == .commandFailed(
                command: "admin history",
                exitCode: 2,
                code: "usage",
                message: "usage: callboard admin [-h]\ncallboard: invalid choice: history"
            ))
            #expect(error?.isTerminal == true)
        }
    }

    @Test func otherNonZeroExitKeepsTheStderrTailWithoutACode() async throws {
        try await CallboardStub.with(script: "echo boom >&2\nexit 1") { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            #expect(error == .commandFailed(command: "admin history", exitCode: 1, code: nil, message: "boom"))
        }
    }

    @Test func garbageStdoutIsMalformed() async throws {
        try await CallboardStub.with(script: "echo 'not json'") { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            guard case let .malformedOutput(command, _) = error else {
                Issue.record("expected malformedOutput, got \(String(describing: error))")
                return
            }
            #expect(command == "admin history")
        }
    }

    @Test func wrongShapeUnderASupportedSchemaIsMalformed() async throws {
        let script = #"echo '{"schema_version":1,"status":"ok","warnings":[]}'"#
        try await CallboardStub.with(script: script) { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            guard case .malformedOutput = error else {
                Issue.record("expected malformedOutput, got \(String(describing: error))")
                return
            }
        }
    }

    @Test func newerSchemaIsUnsupported() async throws {
        let script = #"echo '{"schema_version":2,"status":"ok","warnings":[]}'"#
        try await CallboardStub.with(script: script) { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            #expect(error == .unsupportedSchema(2))
            #expect(error?.isTerminal == true)
        }
    }

    @Test func slowCommandTimesOutAndIsKilled() async throws {
        try await CallboardStub.with(script: "exec sleep 5") { stub in
            let client = CallboardClient(command: stub.command, timeout: .milliseconds(300))
            let clock = ContinuousClock()
            var error: CallboardError?
            let elapsed = await clock.measure { error = await failure(of: client) }
            #expect(error == .timedOut(command: "admin history"))
            #expect(elapsed < .seconds(3))
        }
    }

    @Test func timeoutEndsTheCallWhileADescendantHoldsThePipes() async throws {
        try await CallboardStub.with(script: "sleep 6 &\nexit 0") { stub in
            let client = CallboardClient(command: stub.command, timeout: .milliseconds(300))
            let clock = ContinuousClock()
            var error: CallboardError?
            let elapsed = await clock.measure { error = await failure(of: client) }
            #expect(error == .timedOut(command: "admin history"))
            #expect(elapsed < .seconds(3))
        }
    }

    @Test func childKilledBySigintIsNotAUsageError() async throws {
        try await CallboardStub.with(script: "kill -INT $$") { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            #expect(error == .commandFailed(command: "admin history", exitCode: 2, code: nil, message: ""))
            #expect(error?.isTerminal == false)
        }
    }

    @Test func invalidUtf8InStderrKeepsTheReadableText() async throws {
        try await CallboardStub.with(script: "printf 'bad \\377 byte' >&2\nexit 1") { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            #expect(error == .commandFailed(
                command: "admin history",
                exitCode: 1,
                code: nil,
                message: "bad \u{FFFD} byte"
            ))
        }
    }

    @Test func floodedStderrStillYieldsItsTail() async throws {
        let script = "head -c 3000000 /dev/zero | tr '\\0' e >&2\necho done >&2\nexit 1"
        try await CallboardStub.with(script: script) { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            guard case let .commandFailed(_, _, _, message) = error else {
                Issue.record("expected commandFailed, got \(String(describing: error))")
                return
            }
            #expect(message.hasSuffix("eeeedone"))
            #expect(message.count == 500)
        }
    }

    @Test func aLaunchFailureIsRetriedNotMissing() async throws {
        try await CallboardStub.with(script: "") { stub in
            try "echo hi\n".write(to: stub.command.executable, atomically: true, encoding: .utf8)
            let error = await failure(of: CallboardClient(command: stub.command))
            guard case let .launchFailed(path, _) = error else {
                Issue.record("expected launchFailed, got \(String(describing: error))")
                return
            }
            #expect(path == stub.command.executable.path)
            #expect(error?.isTerminal == false)
        }
    }

    @Test func oversizedStdoutIsMalformed() async throws {
        try await CallboardStub.with(script: "head -c 68000000 /dev/zero | tr '\\0' x") { stub in
            let error = await failure(of: CallboardClient(command: stub.command))
            guard case let .malformedOutput(_, detail) = error else {
                Issue.record("expected malformedOutput, got \(String(describing: error))")
                return
            }
            #expect(detail == "stdout is larger than 64 MB")
        }
    }

    @Test func missingExecutableIsReportedAsNotFound() async {
        let missing = URL(filePath: "/nonexistent/callboard")
        let error = await failure(of: CallboardClient(command: CallboardCommand(executable: missing)))
        #expect(error == .executableNotFound(searched: ["/nonexistent/callboard"]))
        #expect(error?.isTerminal == true)
    }

    @Test func everyErrorHasADescription() {
        let errors: [CallboardError] = [
            .executableNotFound(searched: ["/a", "/b"]),
            .commandFailed(command: "admin history", exitCode: 1, code: nil, message: "boom"),
            .launchFailed(path: "/a", reason: "nope"),
            .malformedOutput(command: "admin history", detail: "bad"),
            .unsupportedSchema(2),
            .timedOut(command: "admin history"),
            .streamEnded(exitCode: 1, standardError: "gone")
        ]
        #expect(errors.compactMap(\.errorDescription) == [
            "callboard was not found; looked in /a, /b",
            "callboard admin history failed (exit 1): boom",
            "callboard could not be started at /a: nope",
            "callboard admin history printed output the app cannot read: bad",
            "callboard speaks schema version 2, which this app does not support",
            "callboard admin history did not finish in time",
            "callboard stopped watching (exit 1): gone"
        ])
    }
}
