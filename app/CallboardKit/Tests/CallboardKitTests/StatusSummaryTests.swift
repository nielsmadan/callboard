import CallboardKit
import Testing

@Suite("StatusSummary")
struct StatusSummaryTests {
    @Test func aLiveFeedShowsTheCount() {
        let summary = StatusSummary(totalNew: 3, state: .live)
        #expect(summary.title == "3")
        #expect(summary.description == "Callboard, 3 new messages")
        #expect(!summary.needsAttention)
    }

    @Test func aLiveFeedWithOneNewMessageSaysMessage() {
        #expect(StatusSummary(totalNew: 1, state: .live).description == "Callboard, 1 new message")
    }

    @Test func aStartingFeedSaysItIsConnecting() {
        let summary = StatusSummary(totalNew: 0, state: .starting)
        #expect(summary.description == "Callboard, connecting")
        #expect(!summary.needsAttention)
    }

    @Test func aReconnectingFeedNeedsAttentionAndKeepsTheCount() {
        let summary = StatusSummary(totalNew: 2, state: .reconnecting("store vanished"))
        #expect(summary.title == "2")
        #expect(summary.description == "Callboard, 2 new messages; reconnecting: store vanished")
        #expect(summary.needsAttention)
    }

    @Test func aFailedFeedNeedsAttentionAndSaysWhy() {
        let summary = StatusSummary(totalNew: 0, state: .failed("callboard was not found"))
        #expect(summary.description == "Callboard is not watching: callboard was not found")
        #expect(summary.needsAttention)
    }
}
