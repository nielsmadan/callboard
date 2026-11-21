import Foundation

public enum AttachmentNaming {
    private static let unsafe = CharacterSet(charactersIn: "/\\:").union(.controlCharacters)

    public static func safeFilename(_ filename: String, fallback: String) -> String {
        let replaced = String(filename.unicodeScalars.map { unsafe.contains($0) ? "_" : Character($0) })
        let name = replaced
            .drop { $0 == "." || $0.isWhitespace }
            .trimmingCharacters(in: .whitespaces)
        return name.isEmpty ? fallback : name
    }
}
