import CallboardKit
import Testing

@Suite("CallboardError")
struct CallboardErrorTests {
    private func failure(_ code: String?) -> CallboardError {
        .commandFailed(command: "admin watch", exitCode: 1, code: code, message: "m")
    }

    @Test(arguments: ["usage", "schema_too_new", "invalid_environment"])
    func errorsNoRetryCanFixAreTerminal(code: String) {
        #expect(failure(code).isTerminal)
    }

    @Test(arguments: ["store_unavailable", "internal_error", nil])
    func otherCommandFailuresAreRetried(code: String?) {
        #expect(!failure(code).isTerminal)
    }
}
