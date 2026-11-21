import AppKit
import CallboardKit
import Observation
import SwiftUI

@MainActor
final class StatusBarManager {
    static let shared = StatusBarManager()

    private var statusItem: NSStatusItem?
    private var popover: NSPopover?
    private var menu: NSMenu?

    private init() {}

    func setup() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        if let button = statusItem?.button {
            button.imagePosition = .imageLeading
            button.action = #selector(handleClick)
            button.target = self
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        let hostingController = NSHostingController(
            rootView: MenuBarView { [weak self] in self?.popover?.performClose(nil) }
                .environment(AppModel.shared)
        )
        hostingController.sizingOptions = .preferredContentSize
        popover = NSPopover()
        popover?.behavior = .transient
        popover?.contentViewController = hostingController

        menu = makeMenu()
        observeStatus()
    }

    private func observeStatus() {
        withObservationTracking {
            let model = AppModel.shared
            apply(StatusSummary(totalNew: model.chats?.totalNew ?? 0, state: model.feedState))
        } onChange: { [weak self] in
            DispatchQueue.main.async { self?.observeStatus() }
        }
    }

    private func apply(_ summary: StatusSummary) {
        guard let button = statusItem?.button else { return }
        let symbol = summary.needsAttention ? "exclamationmark.bubble" : "bubble.left.and.bubble.right"
        let icon = NSImage(systemSymbolName: symbol, accessibilityDescription: "Callboard")
        icon?.isTemplate = true
        button.image = icon
        button.title = summary.title
        button.toolTip = summary.description
        button.setAccessibilityTitle(summary.description)
    }

    private func makeMenu() -> NSMenu {
        let menu = NSMenu()

        let openItem = NSMenuItem(
            title: "Open Callboard",
            action: #selector(WindowManager.openMainWindow),
            keyEquivalent: ""
        )
        openItem.target = WindowManager.shared
        menu.addItem(openItem)

        let settingsItem = NSMenuItem(
            title: "Settings…",
            action: #selector(WindowManager.openSettings),
            keyEquivalent: ","
        )
        settingsItem.target = WindowManager.shared
        menu.addItem(settingsItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        return menu
    }

    @objc private func handleClick() {
        guard let event = NSApp.currentEvent else { return }

        if event.type == .rightMouseUp {
            showMenu()
        } else {
            togglePopover()
        }
    }

    private func showMenu() {
        popover?.performClose(nil)
        statusItem?.menu = menu
        statusItem?.button?.performClick(nil)
        statusItem?.menu = nil
    }

    private func togglePopover() {
        guard let button = statusItem?.button, let popover else { return }

        if popover.isShown {
            popover.performClose(nil)
        } else {
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}
