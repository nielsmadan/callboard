import os

nonisolated enum LogLevel: String, CaseIterable {
    case debug
    case info
    case warning
    case error

    var osLogType: OSLogType {
        switch self {
        case .debug: .debug
        case .info: .info
        case .warning: .default
        case .error: .error
        }
    }
}

nonisolated enum LogCategory: String, CaseIterable {
    case feed
    case client
    case ui
}

nonisolated enum LogManager {
    private static let subsystem = "com.nielsmadan.Callboard"

    static func log(_ level: LogLevel, _ category: LogCategory, _ message: String) {
        Logger(subsystem: subsystem, category: category.rawValue)
            .log(level: level.osLogType, "\(message, privacy: .public)")
    }
}
