public struct FeedConfiguration: Equatable, Sendable {
    public let callboardPath: String?
    public let storeFolder: String?

    public init(callboardPath: String?, storeFolder: String?, home: String) {
        self.callboardPath = Self.expanded(callboardPath, home: home)
        self.storeFolder = Self.expanded(storeFolder, home: home)
    }

    public var environment: [String: String] {
        storeFolder.map { ["XDG_DATA_HOME": $0] } ?? [:]
    }

    public var problem: CallboardError? {
        guard let storeFolder, !storeFolder.hasPrefix("/") else { return nil }
        return .relativeStoreFolder(storeFolder)
    }

    private static func expanded(_ path: String?, home: String) -> String? {
        guard let path, !path.isEmpty else { return nil }
        if path == "~" { return home }
        return path.hasPrefix("~/") ? home + path.dropFirst() : path
    }
}
