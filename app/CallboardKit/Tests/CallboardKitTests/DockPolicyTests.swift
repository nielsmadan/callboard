import CallboardKit
import Testing

@Suite("DockPolicy")
struct DockPolicyTests {
    private func window(
        closing: Bool = false,
        titled: Bool = true,
        panel: Bool = false,
        visible: Bool = true,
        miniaturized: Bool = false
    ) -> WindowState {
        WindowState(
            isClosing: closing,
            isTitled: titled,
            isPanel: panel,
            isSheet: false,
            isVisible: visible,
            isMiniaturized: miniaturized
        )
    }

    @Test func closingTheLastAppWindowHidesDockIcon() {
        #expect(DockPolicy.hidesDockIconAfterClose([window(closing: true)]))
    }

    @Test func closingWindowDoesNotKeepDockIconEvenWhileStillVisible() {
        #expect(DockPolicy.hidesDockIconAfterClose([window(closing: true, visible: true), window(visible: false)]))
    }

    @Test func closingAWindowKeepsDockIconWhileAnotherIsOpen() {
        #expect(DockPolicy.hidesDockIconAfterClose([window(closing: true), window()]) == false)
    }

    @Test func minimizedWindowKeepsDockIconWhenAnotherCloses() {
        #expect(DockPolicy.hidesDockIconAfterClose([
            window(closing: true),
            window(visible: false, miniaturized: true)
        ]) == false)
    }

    @Test func visiblePanelDoesNotKeepDockIconWhenAppWindowCloses() {
        #expect(DockPolicy.hidesDockIconAfterClose([window(closing: true), window(panel: true)]))
    }

    @Test func titledWindowIsAnAppWindow() {
        #expect(DockPolicy.isAppWindow(isTitled: true, isPanel: false, isSheet: false))
    }

    @Test func panelsSheetsAndUntitledWindowsAreNotAppWindows() {
        #expect([
            DockPolicy.isAppWindow(isTitled: true, isPanel: true, isSheet: false),
            DockPolicy.isAppWindow(isTitled: true, isPanel: false, isSheet: true),
            DockPolicy.isAppWindow(isTitled: false, isPanel: false, isSheet: false)
        ] == [false, false, false])
    }

    @Test func minimizedAppWindowKeepsDockIcon() {
        #expect(DockPolicy.keepsDockIcon(isAppWindow: true, isVisible: false, isMiniaturized: true))
    }

    @Test func visibleAppWindowKeepsDockIcon() {
        #expect(DockPolicy.keepsDockIcon(isAppWindow: true, isVisible: true, isMiniaturized: false))
    }

    @Test func closedAppWindowReleasesDockIcon() {
        #expect(DockPolicy.keepsDockIcon(isAppWindow: true, isVisible: false, isMiniaturized: false) == false)
    }

    @Test func visiblePanelReleasesDockIcon() {
        #expect(DockPolicy.keepsDockIcon(isAppWindow: false, isVisible: true, isMiniaturized: false) == false)
    }
}
