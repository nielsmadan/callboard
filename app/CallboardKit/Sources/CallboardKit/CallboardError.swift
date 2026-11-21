import Foundation

public enum CallboardError: LocalizedError, Equatable {
    case executableNotFound(searched: [String])
    case launchFailed(path: String, reason: String)
    case commandFailed(command: String, exitCode: Int32, code: String?, message: String)
    case malformedOutput(command: String, detail: String)
    case unsupportedSchema(Int)
    case timedOut(command: String)
    case streamEnded(exitCode: Int32, standardError: String)
    case relativeStoreFolder(String)

    public var isTerminal: Bool {
        switch self {
        case .executableNotFound, .unsupportedSchema, .relativeStoreFolder:
            true
        case let .commandFailed(_, _, code, _):
            code == "usage" || code == "schema_too_new" || code == "invalid_environment"
        case .launchFailed, .malformedOutput, .timedOut, .streamEnded:
            false
        }
    }

    public var pointsToExecutable: Bool {
        switch self {
        case .relativeStoreFolder: false
        default: true
        }
    }

    public var errorDescription: String? {
        switch self {
        case let .executableNotFound(searched):
            "callboard was not found; looked in \(searched.joined(separator: ", "))"
        case let .launchFailed(path, reason):
            "callboard could not be started at \(path): \(reason)"
        case let .commandFailed(command, exitCode, _, message):
            "callboard \(command) failed (exit \(exitCode)): \(message)"
        case let .malformedOutput(command, detail):
            "callboard \(command) printed output the app cannot read: \(detail)"
        case let .unsupportedSchema(version):
            "callboard speaks schema version \(version), which this app does not support"
        case let .timedOut(command):
            "callboard \(command) did not finish in time"
        case let .streamEnded(exitCode, standardError):
            "callboard stopped watching (exit \(exitCode)): \(standardError)"
        case let .relativeStoreFolder(folder):
            "the store folder must be an absolute path; got \(folder)"
        }
    }
}
