import Foundation
import UniformTypeIdentifiers

public enum OpenPolicy {
    private static let allowedSchemes: Set<String> = ["http", "https", "mailto"]
    private static let riskyExtensions: Set<String> = [
        "terminal", "command", "tool", "jar", "app", "workflow", "scpt", "scptd", "pkg", "dmg", "webloc",
        "inetloc", "fileloc", "url", "mobileconfig", "configprofile", "shortcut", "jnlp", "safariextz"
    ]
    private static let riskyTypes: [UTType] = [.executable, .applicationBundle, .script, .archive]

    public static func isLinkAllowed(_ url: URL) -> Bool {
        url.scheme.map { allowedSchemes.contains($0.lowercased()) } ?? false
    }

    public static func isSafeToOpen(filename: String) -> Bool {
        let ext = (filename as NSString).pathExtension.lowercased()
        if riskyExtensions.contains(ext) { return false }
        guard let type = UTType(filenameExtension: ext) else { return true }
        return !riskyTypes.contains { type.conforms(to: $0) }
    }
}

public enum MessageMarkdown {
    public static func render(_ body: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: body, options: options)) ?? AttributedString(body)
    }
}
