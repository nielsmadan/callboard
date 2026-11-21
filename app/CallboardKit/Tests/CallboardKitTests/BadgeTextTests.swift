import CallboardKit
import Testing

@Suite("BadgeText")
struct BadgeTextTests {
    @Test(arguments: [0, -1, -50])
    func isEmptyWhenNothingIsNew(count: Int) {
        #expect(BadgeText.title(count).isEmpty)
    }

    @Test(arguments: [1, 7, 42, 99])
    func showsTheCount(count: Int) {
        #expect(BadgeText.title(count) == "\(count)")
    }

    @Test(arguments: [100, 101, 5000])
    func capsLargeCounts(count: Int) {
        #expect(BadgeText.title(count) == "99+")
    }
}
