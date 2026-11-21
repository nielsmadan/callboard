import CallboardKit
import ShortcutKit
import Testing

@Suite("ChatsAction")
struct ChatsActionTests {
    @Test func everyDefaultKeyParsesToItsDefinedShortcut() throws {
        let parsed = try ChatsAction.allCases.map { try Shortcut(ascii: $0.defaultKey) }
        #expect(parsed == ChatsAction.allCases.flatMap(\.definition.defaultShortcuts))
    }

    @Test func everyActionHasItsOwnKey() {
        #expect(Set(ChatsAction.allCases.map(\.defaultKey)).count == ChatsAction.allCases.count)
    }
}
