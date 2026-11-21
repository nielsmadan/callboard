public struct WindowState: Sendable {
    public let isClosing: Bool
    public let isTitled: Bool
    public let isPanel: Bool
    public let isSheet: Bool
    public let isVisible: Bool
    public let isMiniaturized: Bool

    public init(
        isClosing: Bool,
        isTitled: Bool,
        isPanel: Bool,
        isSheet: Bool,
        isVisible: Bool,
        isMiniaturized: Bool
    ) {
        self.isClosing = isClosing
        self.isTitled = isTitled
        self.isPanel = isPanel
        self.isSheet = isSheet
        self.isVisible = isVisible
        self.isMiniaturized = isMiniaturized
    }
}

public enum DockPolicy {
    public static func isAppWindow(isTitled: Bool, isPanel: Bool, isSheet: Bool) -> Bool {
        isTitled && !isPanel && !isSheet
    }

    public static func keepsDockIcon(isAppWindow: Bool, isVisible: Bool, isMiniaturized: Bool) -> Bool {
        isAppWindow && (isVisible || isMiniaturized)
    }

    public static func hidesDockIconAfterClose(_ windows: [WindowState]) -> Bool {
        !windows.contains {
            !$0.isClosing && keepsDockIcon(
                isAppWindow: isAppWindow(isTitled: $0.isTitled, isPanel: $0.isPanel, isSheet: $0.isSheet),
                isVisible: $0.isVisible,
                isMiniaturized: $0.isMiniaturized
            )
        }
    }
}
