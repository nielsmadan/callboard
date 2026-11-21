import CallboardKit
import Testing

@Suite("AppSection")
struct AppSectionTests {
    @Test func everySectionHasADistinctTitle() {
        let titles = AppSection.allCases.map(\.title)
        #expect(titles.allSatisfy { !$0.isEmpty })
        #expect(Set(titles).count == titles.count)
    }
}
