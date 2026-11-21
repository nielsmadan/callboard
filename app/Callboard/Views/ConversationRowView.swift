import CallboardKit
import SwiftUI

struct ConversationRowView: View {
    let row: ConversationRow
    let mode: ListMode

    var body: some View {
        HStack(alignment: .center, spacing: 6) {
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: row.title)
                    .fontWeight(row.newCount > 0 ? .bold : .regular)
                    .lineLimit(1)
                if mode == .recent, let preview = previewLine {
                    Text(verbatim: preview)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 2) {
                if mode == .recent, let lastAt = row.lastAt {
                    TimelineView(.everyMinute) { context in
                        Text(verbatim: Formatting.relativeTime(lastAt, now: context.date, calendar: .current))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                if row.newCount > 0 {
                    badge
                }
            }
        }
        .padding(.vertical, mode == .recent ? 3 : 0)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(verbatim: accessibilityText))
    }

    private var previewLine: String? {
        guard let preview = row.preview else { return nil }
        return row.sender.map { "\($0): \(preview)" } ?? preview
    }

    private var badge: some View {
        Text(verbatim: BadgeText.title(row.newCount))
            .font(.caption2.bold())
            .monospacedDigit()
            .foregroundStyle(.white)
            .padding(.horizontal, 6)
            .padding(.vertical, 1)
            .background(Capsule().fill(Color.accentColor))
            .accessibilityHidden(true)
    }

    private var accessibilityText: String {
        let count = row.newCount > 0 ? "\(row.newCount) new" : nil
        return [row.title, count, previewLine].compactMap(\.self).joined(separator: ", ")
    }
}
