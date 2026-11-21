import CallboardKit
import Foundation
import Testing

struct CallboardStub {
    let command: CallboardCommand
    let directory: URL

    var arguments: [String] {
        let text = (try? String(contentsOf: directory.appending(path: "argv.log"), encoding: .utf8)) ?? ""
        return text.split(separator: "\n", omittingEmptySubsequences: true).map(String.init)
    }

    static func with<Result>(
        script: String,
        environment: [String: String] = [:],
        _ body: (CallboardStub) async throws -> Result
    ) async throws -> Result {
        let directory = FileManager.default.temporaryDirectory.appending(path: "callboard-stub-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let executable = directory.appending(path: "callboard")
        let text = "#!/bin/bash\nprintf '%s\\n' \"$@\" > '\(directory.path)/argv.log'\n\(script)\n"
        try text.write(to: executable, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executable.path)
        let stub = CallboardStub(
            command: CallboardCommand(executable: executable, environment: environment),
            directory: directory
        )
        return try await body(stub)
    }
}

enum Fixture {
    static func url(_ name: String) throws -> URL {
        try #require(Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Fixtures"))
    }

    static func data(_ name: String) throws -> Data {
        try Data(contentsOf: url(name))
    }
}
