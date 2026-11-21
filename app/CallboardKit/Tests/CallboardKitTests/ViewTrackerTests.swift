import CallboardKit
import Foundation
import Testing

@Suite("ViewTracker")
@MainActor
struct ViewTrackerTests {
    private let store = Make.store
    private let ops = "group:ops"

    private func withDefaults(_ body: (UserDefaults, String) throws -> Void) throws {
        let name = "callboard-tracker-\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: name))
        defer { defaults.removePersistentDomain(forName: name) }
        try body(defaults, name)
    }

    private func summary(_ seqs: [Int64], firstSeq: Int64? = nil) -> ConversationSummary {
        Make.summary(Make.conversation(ops, seqs: seqs, firstSeq: firstSeq))
    }

    @Test func storeWithoutBaselineCountsNothing() throws {
        try withDefaults { defaults, _ in
            let tracker = LocalViewTracker(defaults: defaults)
            tracker.begin(store: store, snapshot: [])
            #expect(tracker.newCount(for: summary([1, 2, 3])) == 0)
        }
    }

    @Test func snapshotOfOnlyEmptyConversationsStillSetsTheBaseline() throws {
        try withDefaults { defaults, _ in
            let tracker = LocalViewTracker(defaults: defaults)
            tracker.begin(store: store, snapshot: [summary([])])
            #expect(tracker.newCount(for: summary([1, 2])) == 2)
        }
    }

    @Test func baselineCountsUnseenConversationsInFull() throws {
        try withDefaults { defaults, _ in
            let tracker = LocalViewTracker(defaults: defaults)
            tracker.begin(store: store, snapshot: [summary([1, 2])])
            #expect(tracker.newCount(for: summary([1, 2])) == 0)
            #expect(tracker.newCount(for: summary([1, 2, 5])) == 1)
            #expect(tracker.newCount(for: Make.summary(Make.conversation("dm:a:b", seqs: [3, 4]))) == 2)
        }
    }

    @Test func recreatedConversationCountsEveryMessage() throws {
        try withDefaults { defaults, _ in
            let tracker = LocalViewTracker(defaults: defaults)
            tracker.begin(store: store, snapshot: [summary([1, 2, 3])])
            #expect(tracker.newCount(for: summary([8, 9])) == 2)
        }
    }

    @Test func markViewedClearsTheCount() throws {
        try withDefaults { defaults, _ in
            let tracker = LocalViewTracker(defaults: defaults)
            tracker.begin(store: store, snapshot: [summary([1])])
            tracker.markViewed(summary([1, 2, 3]))
            #expect(tracker.newCount(for: summary([1, 2, 3])) == 0)
            #expect(tracker.newCount(for: summary([1, 2, 3, 4])) == 1)
        }
    }

    @Test func marksRoundTripThroughFreshDefaults() throws {
        try withDefaults { defaults, name in
            let first = LocalViewTracker(defaults: defaults, key: "marks")
            first.begin(store: store, snapshot: [summary([1, 2])])
            first.markViewed(summary([1, 2, 3]))
            let reopened = try LocalViewTracker(defaults: #require(UserDefaults(suiteName: name)), key: "marks")
            reopened.begin(store: store, snapshot: [summary([1, 2, 3, 4, 5])])
            #expect(reopened.newCount(for: summary([1, 2, 3, 4, 5])) == 2)
        }
    }

    @Test func markViewedStoresTheConversationsMarkUnderItsStore() throws {
        struct Stored: Decodable {
            let marks: [String: [String: ViewMark]]
        }
        try withDefaults { defaults, _ in
            let tracker = LocalViewTracker(defaults: defaults, key: "marks")
            tracker.begin(store: store, snapshot: [summary([1, 2])])
            tracker.markViewed(summary([1, 2, 3]))
            let data = try #require(defaults.data(forKey: "marks"))
            let mark = try #require(JSONDecoder().decode(Stored.self, from: data).marks[store]?[ops])
            #expect(mark.firstSeq == 1)
            #expect(mark.messages == 3)
        }
    }
}
