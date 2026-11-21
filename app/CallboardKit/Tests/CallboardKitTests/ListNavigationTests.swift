import CallboardKit
import Testing

@Suite("ListNavigation")
struct ListNavigationTests {
    private let ids = ["group:a", "group:b", "group:c", "group:d"]

    private func sections(new: [String: Int] = [:]) -> [RowSection] {
        let conversations = ids.map { Make.summary(Make.conversation($0, name: String($0.suffix(1)))) }
        return ListArrangement.sections(conversations, newCounts: new, mode: .grouped)
    }

    @Test func stepMovesToTheNeighbour() {
        #expect(ListNavigation.step(from: "group:b", by: 1, in: sections()) == "group:c")
        #expect(ListNavigation.step(from: "group:b", by: -1, in: sections()) == "group:a")
    }

    @Test func stepStopsAtEitherEnd() {
        #expect(ListNavigation.step(from: "group:d", by: 1, in: sections()) == "group:d")
        #expect(ListNavigation.step(from: "group:a", by: -1, in: sections()) == "group:a")
    }

    @Test func stepWithoutASelectionStartsAtTheFirstOrLastRow() {
        #expect(ListNavigation.step(from: nil, by: 1, in: sections()) == "group:a")
        #expect(ListNavigation.step(from: "group:gone", by: -1, in: sections()) == "group:d")
    }

    @Test func stepInAnEmptyListSelectsNothing() {
        #expect(ListNavigation.step(from: nil, by: 1, in: []) == nil)
    }

    @Test func nextWithNewSearchesForwardFromTheSelection() {
        let rows = sections(new: ["group:a": 1, "group:d": 2])
        #expect(ListNavigation.nextWithNew(after: "group:b", in: rows) == "group:d")
    }

    @Test func nextWithNewWrapsAroundToTheTop() {
        let rows = sections(new: ["group:a": 1, "group:c": 2])
        #expect(ListNavigation.nextWithNew(after: "group:c", in: rows) == "group:a")
    }

    @Test func nextWithNewSkipsTheSelectedRow() {
        let rows = sections(new: ["group:b": 3])
        #expect(ListNavigation.nextWithNew(after: "group:b", in: rows) == nil)
        #expect(ListNavigation.nextWithNew(after: nil, in: rows) == "group:b")
    }
}
