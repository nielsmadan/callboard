import Foundation

public struct ConversationRow: Identifiable, Equatable, Sendable {
    public let id: String
    public let kind: ConversationKind
    public let title: String
    public let sender: String?
    public let preview: String?
    public let lastAt: Date?
    public let newCount: Int
}

public struct RowSection: Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String?
    public let rows: [ConversationRow]
}

extension ConversationKind {
    var isChat: Bool {
        self == .dm || self == .group
    }
}

public enum ListArrangement {
    public static func sections(
        _ conversations: [ConversationSummary],
        newCounts: [String: Int],
        mode: ListMode
    ) -> [RowSection] {
        let rows = conversations.filter(\.kind.isChat).map { row(for: $0, newCount: newCounts[$0.id] ?? 0) }
        switch mode {
        case .grouped:
            let groups = rows.filter { $0.kind == .group }.sorted(by: byTitle)
            let dms = rows.filter { $0.kind == .dm }.sorted(by: byTitle)
            return [
                RowSection(id: "groups", title: "Groups", rows: groups),
                RowSection(id: "dms", title: "Direct messages", rows: dms)
            ].filter { !$0.rows.isEmpty }
        case .recent:
            let seqs = Dictionary(
                conversations.compactMap { summary in summary.last.map { (summary.id, $0.seq) } },
                uniquingKeysWith: { $1 }
            )
            let sorted = rows.sorted { byRecency(seqs[$0.id], seqs[$1.id], $0, $1) }
            return rows.isEmpty ? [] : [RowSection(id: "recent", title: nil, rows: sorted)]
        }
    }

    public static func title(of conversation: ConversationSummary) -> String {
        switch conversation.kind {
        case .group:
            conversation.name.map { "#\($0)" } ?? conversation.id
        case .dm:
            conversation.members.joined(separator: " ↔ ")
        case .mail, .topic, .unknown:
            conversation.subject ?? conversation.name ?? conversation.id
        }
    }

    private static func row(for conversation: ConversationSummary, newCount: Int) -> ConversationRow {
        ConversationRow(
            id: conversation.id,
            kind: conversation.kind,
            title: title(of: conversation),
            sender: conversation.last?.sender,
            preview: conversation.last?.preview,
            lastAt: conversation.last?.createdAt,
            newCount: newCount
        )
    }

    private static func byTitle(_ lhs: ConversationRow, _ rhs: ConversationRow) -> Bool {
        switch lhs.title.caseInsensitiveCompare(rhs.title) {
        case .orderedAscending: true
        case .orderedDescending: false
        case .orderedSame: lhs.id < rhs.id
        }
    }

    private static func byRecency(
        _ lhsSeq: Int64?,
        _ rhsSeq: Int64?,
        _ lhs: ConversationRow,
        _ rhs: ConversationRow
    ) -> Bool {
        switch (lhsSeq, rhsSeq) {
        case let (left?, right?): left == right ? byTitle(lhs, rhs) : left > right
        case (.some, nil): true
        case (nil, .some): false
        case (nil, nil): byTitle(lhs, rhs)
        }
    }
}
