import CallboardKit
import Foundation
import Testing

@Suite("Formatting")
struct FormattingTests {
    private let calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        calendar.locale = Locale(identifier: "en_US_POSIX")
        return calendar
    }()

    private func date(_ text: String) throws -> Date {
        try #require(ISO8601DateFormatter().date(from: text))
    }

    @Test func todayShowsTheTime() throws {
        let text = try Formatting.relativeTime(
            date("2026-11-21T09:05:00Z"),
            now: date("2026-11-21T17:00:00Z"),
            calendar: calendar
        )
        #expect(text.hasPrefix("9:05"))
    }

    @Test func timeUsesTheCalendarsTimeZone() throws {
        var tokyo = calendar
        tokyo.timeZone = TimeZone(identifier: "Asia/Tokyo") ?? .gmt
        let text = try Formatting.relativeTime(
            date("2026-11-21T09:05:00Z"),
            now: date("2026-11-21T10:00:00Z"),
            calendar: tokyo
        )
        #expect(text.hasPrefix("6:05"))
    }

    @Test func previousDayShowsYesterday() throws {
        let text = try Formatting.relativeTime(
            date("2026-11-20T23:59:00Z"),
            now: date("2026-11-21T00:01:00Z"),
            calendar: calendar
        )
        #expect(text == "Yesterday")
    }

    @Test func olderDaysShowAShortDate() throws {
        let text = try Formatting.relativeTime(
            date("2026-11-12T09:05:00Z"),
            now: date("2026-11-21T17:00:00Z"),
            calendar: calendar
        )
        #expect(text == "11/12/2026")
    }

    @Test func replyQuotesTheLoadedParentsFirstLine() {
        let thread = [
            Make.chatMessage(Make.message(1, in: "group:ops", body: "deploy at noon\nthen verify")),
            Make.chatMessage(Make.message(2, in: "group:ops", body: "on it", parent: "cb_1"))
        ]
        #expect(Formatting.replyQuote(for: thread[1], in: thread) == .parent(sender: "enki", line: "deploy at noon"))
        #expect(Formatting.replyQuote(for: thread[0], in: thread) == nil)
    }

    @Test func replyToAnUnloadedParentNamesItsId() {
        let reply = Make.chatMessage(Make.message(9, in: "group:ops", parent: "cb_3"))
        #expect(Formatting.replyQuote(for: reply, in: [reply]) == .unloaded(parentId: "cb_3"))
    }
}
