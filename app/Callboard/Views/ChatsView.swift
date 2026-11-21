import AppKit
import CallboardKit
import SwiftUI

struct ChatsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.controlActiveState) private var controlActiveState
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage(AppStorageKeys.listMode) private var listMode: ListMode = .grouped

    private var isKey: Bool {
        controlActiveState == .key
    }

    @State private var selecting: Task<Void, Never>?
    @State private var isWindowVisible = true
    @State private var isScreenAsleep = false
    @State private var isScreenLocked = false

    private var isViewing: Bool {
        ViewingConditions(
            isKeyWindow: isKey,
            isActive: scenePhase == .active,
            isWindowVisible: isWindowVisible,
            isScreenAsleep: isScreenAsleep,
            isScreenLocked: isScreenLocked
        ).isViewing
    }

    private static func keyWindowIsVisible() -> Bool {
        NSApp.keyWindow?.occlusionState.contains(.visible) ?? true
    }

    var body: some View {
        FeedStatusView(
            state: model.feedState,
            store: model.chats?.store,
            isEmpty: model.chats?.chatConversations.isEmpty ?? true,
            executablePath: model.executablePath,
            showsInstallHint: model.showsInstallHint
        ) {
            if let chats = model.chats {
                split(chats)
            }
        }
        .frame(minWidth: 640, minHeight: 400)
        .keyWindowShortcutContext(ShortcutCenter.shared.chatsContext, isActive: isKey) { action, _ in
            perform(action)
        }
        .onChange(of: isViewing, initial: true) { _, viewing in
            model.isViewing = viewing
        }
        .onDisappear {
            model.isViewing = false
        }
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didChangeOcclusionStateNotification)) { _ in
            isWindowVisible = Self.keyWindowIsVisible()
        }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.screensDidSleepNotification)) { _ in
            isScreenAsleep = true
        }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.screensDidWakeNotification)) { _ in
            isScreenAsleep = false
        }
        .onReceive(DistributedNotificationCenter.default().publisher(for: .init("com.apple.screenIsLocked"))) { _ in
            isScreenLocked = true
        }
        .onReceive(DistributedNotificationCenter.default().publisher(for: .init("com.apple.screenIsUnlocked"))) { _ in
            isScreenLocked = false
            isWindowVisible = Self.keyWindowIsVisible()
        }
    }

    private func split(_ chats: ChatStore) -> some View {
        NavigationSplitView {
            ConversationListView(
                sections: chats.sections(mode: listMode),
                mode: listMode,
                selection: Binding(get: { chats.selectedId }, set: { select($0, in: chats) })
            )
            .navigationSplitViewColumnWidth(min: 220, ideal: 280, max: 420)
        } detail: {
            if let selectedId = chats.selectedId,
               let conversation = chats.conversations.first(where: { $0.id == selectedId }) {
                ConversationDetailView(
                    conversation: conversation,
                    thread: chats.thread,
                    loadOlder: { Task { await chats.loadOlder() } },
                    retry: { Task { await chats.select(selectedId) } }
                )
                .id(selectedId)
            } else {
                ContentUnavailableView("Select a conversation", systemImage: "bubble.left.and.bubble.right")
            }
        }
    }

    private func select(_ conversationId: String?, in chats: ChatStore) {
        guard conversationId != chats.selectedId else { return }
        selecting?.cancel()
        selecting = Task { await chats.select(conversationId) }
    }

    private func perform(_ action: ChatsAction) {
        switch action {
        case .showGrouped:
            listMode = .grouped
        case .showRecent:
            listMode = .recent
        case .toggleListMode:
            listMode = listMode == .grouped ? .recent : .grouped
        case .nextConversation:
            move(by: 1)
        case .previousConversation:
            move(by: -1)
        case .nextWithNew:
            selectNextWithNew()
        case .loadOlder:
            if let chats = model.chats {
                Task { await chats.loadOlder() }
            }
        }
    }

    private func move(by offset: Int) {
        guard let chats = model.chats,
              let target = ListNavigation.step(from: chats.selectedId, by: offset, in: chats.sections(mode: listMode))
        else { return }
        select(target, in: chats)
    }

    private func selectNextWithNew() {
        guard let chats = model.chats,
              let next = ListNavigation.nextWithNew(after: chats.selectedId, in: chats.sections(mode: listMode))
        else { return }
        select(next, in: chats)
    }
}
