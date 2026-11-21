import AppKit
import CallboardKit
import SwiftUI

@MainActor
final class WindowManager: NSObject {
    enum SceneID {
        static let main = "main"
    }

    static let shared = WindowManager()

    private let defaults: UserDefaults
    private var mainWindowOpener: (() -> Void)?
    private var settingsWindow: NSWindow?
    private var mainWindowNeedsRestore = true
    private var hideDockIconWorkItem: DispatchWorkItem?

    private init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        super.init()
    }

    private var mainWindow: NSWindow? {
        NSApp.windows.first(where: isMainWindow)
    }

    private func isMainWindow(_ window: NSWindow) -> Bool {
        window.identifier?.rawValue == SceneID.main
    }

    func start() {
        activateApp()
        observeWindows()
        restoreMainWindowFrameAtLaunch()
    }

    private func observeWindows() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(windowWillClose),
            name: NSWindow.willCloseNotification,
            object: nil
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(windowDidBecomeKey),
            name: NSWindow.didBecomeKeyNotification,
            object: nil
        )
    }

    // Only `Commands` can reach `openWindow` before the main scene has created a window.
    func registerMainWindowOpener(_ opener: @escaping () -> Void) {
        guard mainWindowOpener == nil else { return }
        mainWindowOpener = opener
    }

    @objc func openMainWindow() {
        if let window = mainWindow {
            activateApp()
            window.makeKeyAndOrderFront(nil)
            window.orderFrontRegardless()
        } else if let mainWindowOpener {
            activateApp()
            mainWindowOpener()
        } else {
            LogManager.log(.warning, .ui, "main window opener is not registered; cannot open the main window")
        }
    }

    @objc func openSettings() {
        activateApp()

        if settingsWindow == nil {
            let hostingController = NSHostingController(
                rootView: SettingsView()
                    .environment(AppModel.shared)
            )
            let window = NSWindow(contentViewController: hostingController)
            window.title = "Settings"
            window.styleMask = [.titled, .closable, .resizable]
            window.isReleasedWhenClosed = false
            window.center()
            settingsWindow = window
        }

        settingsWindow?.makeKeyAndOrderFront(nil)
    }

    // The Dock policy must change before activation, or the previous app keeps the menu bar.
    private func activateApp() {
        showDockIcon()
        NSApp.activate()
    }

    private func showDockIcon() {
        cancelPendingDockHide()
        NSApp.setActivationPolicy(.regular)
    }

    private func cancelPendingDockHide() {
        hideDockIconWorkItem?.cancel()
        hideDockIconWorkItem = nil
    }

    private func scheduleDockIconHide() {
        cancelPendingDockHide()
        let workItem = DispatchWorkItem {
            NSApp.setActivationPolicy(.accessory)
        }
        hideDockIconWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1, execute: workItem)
    }

    private func restoreMainWindowFrameAtLaunch() {
        guard defaults.string(forKey: AppStorageKeys.mainWindowFrame) != nil else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, let window = mainWindow else { return }
            window.alphaValue = 0
            restoreSavedFrame(for: window)
            window.alphaValue = 1
        }
    }

    private func restoreSavedFrame(for window: NSWindow) {
        mainWindowNeedsRestore = false
        guard let frameString = defaults.string(forKey: AppStorageKeys.mainWindowFrame) else { return }
        let savedFrame = NSRectFromString(frameString)
        let onScreen = NSScreen.screens.contains(where: { $0.visibleFrame.intersects(savedFrame) })
        if savedFrame.width > 100, savedFrame.height > 100, onScreen {
            window.setFrame(savedFrame, display: false)
        }
    }

    private static func isAppWindow(_ window: NSWindow) -> Bool {
        DockPolicy.isAppWindow(
            isTitled: window.styleMask.contains(.titled),
            isPanel: window is NSPanel,
            isSheet: window.sheetParent != nil
        )
    }

    @objc private func windowWillClose(_ notification: Notification) {
        guard let window = notification.object as? NSWindow, Self.isAppWindow(window) else { return }

        if isMainWindow(window) {
            defaults.set(NSStringFromRect(window.frame), forKey: AppStorageKeys.mainWindowFrame)
            mainWindowNeedsRestore = true
        }

        let states = NSApp.windows.map { other in
            WindowState(
                isClosing: other === window,
                isTitled: other.styleMask.contains(.titled),
                isPanel: other is NSPanel,
                isSheet: other.sheetParent != nil,
                isVisible: other.isVisible,
                isMiniaturized: other.isMiniaturized
            )
        }
        if DockPolicy.hidesDockIconAfterClose(states) {
            scheduleDockIconHide()
        }
    }

    @objc private func windowDidBecomeKey(_ notification: Notification) {
        guard let window = notification.object as? NSWindow, Self.isAppWindow(window) else { return }
        showDockIcon()
        if isMainWindow(window), mainWindowNeedsRestore {
            restoreSavedFrame(for: window)
        }
    }
}
