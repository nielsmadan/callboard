public enum BadgeText {
    public static func title(_ count: Int) -> String {
        if count <= 0 { "" } else if count > 99 { "99+" } else { String(count) }
    }
}
