import Foundation

public struct CallboardCommand: Sendable, Equatable {
    public let executable: URL
    public let environment: [String: String]

    public init(executable: URL, environment: [String: String] = [:]) {
        self.executable = executable
        self.environment = environment
    }
}

public enum Resolution: Sendable, Equatable {
    case found(URL)
    case notFound(searched: [String])
}

public enum ExecutableLocator {
    public static func candidates(home: URL) -> [URL] {
        [
            home.appending(path: ".local/bin/callboard"),
            URL(filePath: "/opt/homebrew/bin/callboard"),
            URL(filePath: "/usr/local/bin/callboard")
        ]
    }

    public static func resolve(override: String?, home: URL, isExecutable: (String) -> Bool) -> Resolution {
        if let override, !override.isEmpty {
            return isExecutable(override) ? .found(URL(filePath: override)) : .notFound(searched: [override])
        }
        let all = candidates(home: home)
        return all.first { isExecutable($0.path) }.map(Resolution.found)
            ?? .notFound(searched: all.map(\.path))
    }

    public static func awaitExecutable(
        every interval: Duration,
        isolation _: isolated (any Actor)? = #isolation,
        resolve: () -> Resolution,
        report: (Resolution) -> Void
    ) async -> URL? {
        while !Task.isCancelled {
            let resolution = resolve()
            report(resolution)
            if case let .found(url) = resolution { return url }
            try? await Task.sleep(for: interval)
        }
        return nil
    }
}
