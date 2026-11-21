public struct ViewingConditions: Equatable, Sendable {
    public let isKeyWindow: Bool
    public let isActive: Bool
    public let isWindowVisible: Bool
    public let isScreenAsleep: Bool
    public let isScreenLocked: Bool

    public init(isKeyWindow: Bool, isActive: Bool, isWindowVisible: Bool, isScreenAsleep: Bool, isScreenLocked: Bool) {
        self.isKeyWindow = isKeyWindow
        self.isActive = isActive
        self.isWindowVisible = isWindowVisible
        self.isScreenAsleep = isScreenAsleep
        self.isScreenLocked = isScreenLocked
    }

    public var isViewing: Bool {
        isKeyWindow && isActive && isWindowVisible && !isScreenAsleep && !isScreenLocked
    }
}
