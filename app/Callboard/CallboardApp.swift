import CallboardKit
import ShortcutKit
import SwiftUI

private func otherRunningInstance() -> NSRunningApplication? {
    guard let bundleID = Bundle.main.bundleIdentifier else { return nil }
    return NSRunningApplication.runningApplications(withBundleIdentifier: bundleID)
        .first { $0 != .current && !$0.isTerminated }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_: NSApplication) -> Bool {
        false
    }

    func applicationDidFinishLaunching(_: Notification) {
        if let existing = otherRunningInstance() {
            existing.activate()
            NSApp.terminate(nil)
            return
        }

        WindowManager.shared.start()
        StatusBarManager.shared.setup()
        AppModel.shared.start()
    }
}

@main
struct CallboardApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        Window("Callboard", id: WindowManager.SceneID.main) {
            ChatsView()
                .environment(AppModel.shared)
        }
        .defaultSize(width: 900, height: 600)
        .commands {
            AppCommands()
        }
    }
}

struct AppCommands: Commands {
    @Environment(\.openWindow) private var openWindow
    @AppStorage(AppStorageKeys.listMode) private var listMode: ListMode = .grouped

    var body: some Commands {
        // swiftlint:disable:next redundant_discardable_let
        let _ = WindowManager.shared.registerMainWindowOpener { openWindow(id: WindowManager.SceneID.main) }

        CommandGroup(replacing: .appSettings) {
            Button("Settings…") {
                WindowManager.shared.openSettings()
            }
            .keyboardShortcut(",")
        }

        CommandGroup(after: .toolbar) {
            Toggle("As Groups and Direct Messages", isOn: isListMode(.grouped))
                .shortcut(ChatsAction.showGrouped, in: ShortcutCenter.shared.chatsContext)
            Toggle("Most Recent First", isOn: isListMode(.recent))
                .shortcut(ChatsAction.showRecent, in: ShortcutCenter.shared.chatsContext)
        }
    }

    private func isListMode(_ mode: ListMode) -> Binding<Bool> {
        Binding(get: { listMode == mode }, set: { _ in listMode = mode })
    }
}
