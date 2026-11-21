import Foundation
import ShortcutKit

public enum ChatsAction: String, ShortcutAction {
    case showGrouped
    case showRecent
    case toggleListMode
    case nextConversation
    case previousConversation
    case nextWithNew
    case loadOlder

    public var defaultKey: String {
        switch self {
        case .showGrouped: "cmd+1"
        case .showRecent: "cmd+2"
        case .toggleListMode: "cmd+shift+l"
        case .nextConversation: "opt+down"
        case .previousConversation: "opt+up"
        case .nextWithNew: "opt+shift+down"
        case .loadOlder: "cmd+shift+up"
        }
    }

    public var definition: ShortcutActionDefinition {
        .init(displayName, Shortcut(stringLiteral: defaultKey), allowsKeyRepeat: allowsKeyRepeat)
    }

    private var displayName: LocalizedStringResource {
        switch self {
        case .showGrouped: "Groups and Direct Messages"
        case .showRecent: "Most Recent First"
        case .toggleListMode: "Toggle List Mode"
        case .nextConversation: "Next Conversation"
        case .previousConversation: "Previous Conversation"
        case .nextWithNew: "Next With New Messages"
        case .loadOlder: "Load Older Messages"
        }
    }

    private var allowsKeyRepeat: Bool {
        switch self {
        case .nextConversation, .previousConversation, .nextWithNew: true
        case .showGrouped, .showRecent, .toggleListMode, .loadOlder: false
        }
    }
}
