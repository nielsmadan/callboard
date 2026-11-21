import CallboardKit
import Foundation
import Testing

@Suite("ListArrangement")
struct ListArrangementTests {
    private let conversations = [
        Make.conversation("group:ops", name: "ops", seqs: [1, 4]),
        Make.conversation("dm:nanna:niels", members: ["nanna", "niels"], seqs: [2]),
        Make.conversation("group:Alpha", name: "Alpha", seqs: [5]),
        Make.conversation("dm:enki:nanna", members: ["enki", "nanna"]),
        Make.conversation("group:build", name: "build"),
        Make.conversation("mail:7", seqs: [6])
    ].map(Make.summary)

    @Test func groupedListsGroupsThenDirectMessagesAlphabetically() {
        let sections = ListArrangement.sections(conversations, newCounts: ["group:ops": 2], mode: .grouped)
        #expect(sections.map(\.title) == ["Groups", "Direct messages"])
        #expect(sections[0].rows.map(\.title) == ["#Alpha", "#build", "#ops"])
        #expect(sections[1].rows.map(\.title) == ["enki ↔ nanna", "nanna ↔ niels"])
        #expect(sections[0].rows.map(\.newCount) == [0, 0, 2])
    }

    @Test func groupedOmitsEmptySections() {
        let sections = ListArrangement.sections(Array(conversations.prefix(1)), newCounts: [:], mode: .grouped)
        #expect(sections.map(\.id) == ["groups"])
    }

    @Test func recentOrdersByLatestMessageWithSilentConversationsLast() {
        let sections = ListArrangement.sections(conversations, newCounts: [:], mode: .recent)
        #expect(sections.count == 1)
        #expect(sections[0].title == nil)
        #expect(sections[0].rows.map(\.id) == [
            "group:Alpha",
            "group:ops",
            "dm:nanna:niels",
            "group:build",
            "dm:enki:nanna"
        ])
        let latest = sections[0].rows[0]
        #expect(latest.sender == "enki")
        #expect(latest.preview == "hello")
        #expect(latest.lastAt == ISO8601DateFormatter().date(from: Make.createdAt))
    }

    @Test func everyModeListsOnlyTheChats() {
        let chats: Set = ["group:ops", "dm:nanna:niels", "group:Alpha", "dm:enki:nanna", "group:build"]
        for mode in ListMode.allCases {
            let ids = ListArrangement.sections(conversations, newCounts: [:], mode: mode).flatMap(\.rows).map(\.id)
            #expect(Set(ids) == chats)
            #expect(ids.count == chats.count)
        }
    }

    @Test func otherKindsAreTitledBySubjectOrId() {
        #expect(ListArrangement.title(of: conversations[5]) == "mail:7")
    }
}
