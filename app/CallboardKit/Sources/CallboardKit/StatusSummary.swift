public struct StatusSummary: Equatable, Sendable {
    public let title: String
    public let description: String
    public let needsAttention: Bool

    public init(totalNew: Int, state: FeedState) {
        title = BadgeText.title(totalNew)
        let count = "\(totalNew) new \(totalNew == 1 ? "message" : "messages")"
        switch state {
        case .starting:
            description = "Callboard, connecting"
            needsAttention = false
        case .live:
            description = "Callboard, \(count)"
            needsAttention = false
        case let .reconnecting(reason):
            description = "Callboard, \(count); reconnecting: \(reason)"
            needsAttention = true
        case let .failed(reason):
            description = "Callboard is not watching: \(reason)"
            needsAttention = true
        }
    }
}
