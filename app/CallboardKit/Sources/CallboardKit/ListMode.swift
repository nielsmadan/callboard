public enum ListMode: String, CaseIterable, Sendable {
    case grouped
    case recent
}

public enum AppSection: String, CaseIterable, Sendable {
    case chats

    public var title: String {
        switch self {
        case .chats: "Chats"
        }
    }
}
