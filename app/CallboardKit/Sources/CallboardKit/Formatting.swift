import Foundation

public enum ReplyQuote: Equatable, Sendable {
    case parent(sender: String, line: String)
    case unloaded(parentId: String)
}

public enum Formatting {
    public static func relativeTime(_ date: Date, now: Date, calendar: Calendar) -> String {
        if calendar.isDate(date, inSameDayAs: now) {
            return date.formatted(style(date: .omitted, time: .shortened, calendar: calendar))
        }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now),
           calendar.isDate(date, inSameDayAs: yesterday) {
            return "Yesterday"
        }
        return date.formatted(style(date: .numeric, time: .omitted, calendar: calendar))
    }

    public static func replyQuote(for message: ChatMessage, in thread: [ChatMessage]) -> ReplyQuote? {
        guard let parentId = message.parentId else { return nil }
        guard let parent = thread.first(where: { $0.id == parentId }) else { return .unloaded(parentId: parentId) }
        let line = parent.body.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
        return .parent(sender: parent.sender, line: line)
    }

    private static func style(
        date: Date.FormatStyle.DateStyle,
        time: Date.FormatStyle.TimeStyle,
        calendar: Calendar
    ) -> Date.FormatStyle {
        Date.FormatStyle(
            date: date,
            time: time,
            locale: calendar.locale ?? .current,
            calendar: calendar,
            timeZone: calendar.timeZone
        )
    }
}
