import CallboardKit
import ShortcutKit
import SwiftUI

@MainActor
final class ShortcutCenter {
    static let shared = ShortcutCenter()

    let chatsContext = ShortcutContext<ChatsAction>("chats", displayName: "Chats")
    // Contexts hold their registry weakly, so this reference keeps it alive.
    let registry: ShortcutRegistry

    private init() {
        registry = ShortcutRegistry(contexts: [chatsContext])
    }
}

extension View {
    // Key-window gating scopes ShortcutKit's per-activation handler to the receiving window.
    func keyWindowShortcutContext<A: ShortcutAction>(
        _ context: ShortcutContext<A>,
        isActive: Bool,
        dispatch handler: @escaping @MainActor (A, ShortcutDispatch) -> Void
    ) -> some View {
        background(
            Group {
                if isActive {
                    Color.clear
                        .frame(width: 0, height: 0)
                        .activeShortcutContext(context, dispatch: handler)
                }
            }
        )
    }
}
