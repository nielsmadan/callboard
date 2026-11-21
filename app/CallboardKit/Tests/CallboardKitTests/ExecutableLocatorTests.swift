import CallboardKit
import Foundation
import Testing

@Suite("ExecutableLocator")
struct ExecutableLocatorTests {
    private let home = URL(filePath: "/Users/tester")

    @Test func candidatesAreTheUserBinThenHomebrewThenUsrLocal() {
        #expect(ExecutableLocator.candidates(home: home).map(\.path) == [
            "/Users/tester/.local/bin/callboard",
            "/opt/homebrew/bin/callboard",
            "/usr/local/bin/callboard"
        ])
    }

    @Test func overrideWinsOverEveryCandidate() {
        let resolution = ExecutableLocator.resolve(override: "/custom/callboard", home: home) { _ in true }
        #expect(resolution == .found(URL(filePath: "/custom/callboard")))
    }

    @Test func overrideNeverFallsBackToACandidate() {
        let resolution = ExecutableLocator.resolve(override: "/custom/callboard", home: home) {
            $0 == "/opt/homebrew/bin/callboard"
        }
        #expect(resolution == .notFound(searched: ["/custom/callboard"]))
    }

    @Test func firstExecutableCandidateIsReturned() {
        let executable: Set = ["/opt/homebrew/bin/callboard", "/usr/local/bin/callboard"]
        let resolution = ExecutableLocator.resolve(override: nil, home: home) { executable.contains($0) }
        #expect(resolution == .found(URL(filePath: "/opt/homebrew/bin/callboard")))
    }

    @Test func emptyOverrideUsesTheCandidates() {
        let resolution = ExecutableLocator.resolve(override: "", home: home) { $0 == "/usr/local/bin/callboard" }
        #expect(resolution == .found(URL(filePath: "/usr/local/bin/callboard")))
    }

    @Test func nothingExecutableListsEveryCandidate() {
        let resolution = ExecutableLocator.resolve(override: nil, home: home) { _ in false }
        #expect(resolution == .notFound(searched: [
            "/Users/tester/.local/bin/callboard",
            "/opt/homebrew/bin/callboard",
            "/usr/local/bin/callboard"
        ]))
    }

    @Test func awaitingKeepsLookingUntilTheExecutableAppears() async {
        let installed = URL(filePath: "/Users/tester/.local/bin/callboard")
        let missing = Resolution.notFound(searched: [installed.path])
        var answers = [missing, missing, .found(installed)]
        var reports: [Resolution] = []
        let url = await ExecutableLocator.awaitExecutable(
            every: .zero,
            resolve: { answers.removeFirst() },
            report: { reports.append($0) }
        )
        #expect(url == installed)
        #expect(reports == [missing, missing, .found(installed)])
    }
}
