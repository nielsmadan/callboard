import CallboardKit
import Testing

@Suite("ViewingConditions")
struct ViewingConditionsTests {
    @Test func aVisibleKeyWindowOnAnAwakeUnlockedScreenIsViewing() {
        let conditions = ViewingConditions(
            isKeyWindow: true,
            isActive: true,
            isWindowVisible: true,
            isScreenAsleep: false,
            isScreenLocked: false
        )
        #expect(conditions.isViewing)
    }

    @Test(arguments: 0 ..< 5)
    func anyFailingConditionStopsViewing(failing: Int) {
        let conditions = ViewingConditions(
            isKeyWindow: failing != 0,
            isActive: failing != 1,
            isWindowVisible: failing != 2,
            isScreenAsleep: failing == 3,
            isScreenLocked: failing == 4
        )
        #expect(!conditions.isViewing)
    }
}
