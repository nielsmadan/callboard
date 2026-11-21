public enum ListNavigation {
    public static func step(from selected: String?, by offset: Int, in sections: [RowSection]) -> String? {
        let ids = sections.flatMap(\.rows).map(\.id)
        guard !ids.isEmpty else { return nil }
        let target = selected
            .flatMap(ids.firstIndex(of:))
            .map { min(max($0 + offset, 0), ids.count - 1) }
            ?? (offset > 0 ? 0 : ids.count - 1)
        return ids[target]
    }

    public static func nextWithNew(after selected: String?, in sections: [RowSection]) -> String? {
        let rows = sections.flatMap(\.rows)
        let start = selected.flatMap { id in rows.firstIndex { $0.id == id } }.map { $0 + 1 } ?? 0
        return (rows[start...] + rows[..<start]).first { $0.newCount > 0 && $0.id != selected }?.id
    }
}
