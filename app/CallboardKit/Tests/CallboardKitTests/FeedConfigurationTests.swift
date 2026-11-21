import CallboardKit
import Testing

@Suite("FeedConfiguration")
struct FeedConfigurationTests {
    private let home = "/Users/tester"

    @Test func aStoreFolderBecomesTheDataHome() {
        let configuration = FeedConfiguration(callboardPath: nil, storeFolder: "/srv/callboard", home: home)
        #expect(configuration.environment == ["XDG_DATA_HOME": "/srv/callboard"])
        #expect(configuration.problem == nil)
    }

    @Test(arguments: [nil, ""])
    func noStoreFolderLeavesTheEnvironmentAlone(folder: String?) {
        let configuration = FeedConfiguration(callboardPath: "", storeFolder: folder, home: home)
        #expect(configuration.environment.isEmpty)
        #expect(configuration.storeFolder == nil)
        #expect(configuration.callboardPath == nil)
    }

    @Test func aTildeExpandsToTheHomeFolder() {
        let configuration = FeedConfiguration(callboardPath: "~/bin/callboard", storeFolder: "~/data", home: home)
        #expect(configuration.environment == ["XDG_DATA_HOME": "/Users/tester/data"])
        #expect(configuration.callboardPath == "/Users/tester/bin/callboard")
        #expect(FeedConfiguration(callboardPath: nil, storeFolder: "~", home: home).storeFolder == home)
    }

    @Test(arguments: ["data", "./data", "~other/data"])
    func aRelativeStoreFolderIsATerminalProblem(folder: String) throws {
        let problem = try #require(FeedConfiguration(callboardPath: nil, storeFolder: folder, home: home).problem)
        #expect(problem == .relativeStoreFolder(folder))
        #expect(problem.isTerminal)
        #expect(!problem.pointsToExecutable)
        #expect(problem.localizedDescription == "the store folder must be an absolute path; got \(folder)")
    }

    @Test
    func executableFailuresPointToTheExecutable() {
        #expect(CallboardError.executableNotFound(searched: ["/usr/bin"]).pointsToExecutable)
        #expect(CallboardError.unsupportedSchema(2).pointsToExecutable)
    }
}
