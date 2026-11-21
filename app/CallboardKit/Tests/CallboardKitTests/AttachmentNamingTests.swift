import CallboardKit
import Testing

@Suite("AttachmentNaming")
struct AttachmentNamingTests {
    private func safe(_ filename: String) -> String {
        AttachmentNaming.safeFilename(filename, fallback: "at_000000000007")
    }

    @Test func plainNameIsKept() {
        #expect(safe("notes v2.txt") == "notes v2.txt")
    }

    @Test(arguments: [
        ("reports/q3.txt", "reports_q3.txt"),
        ("reports\\q3.txt", "reports_q3.txt"),
        ("reports:q3.txt", "reports_q3.txt")
    ])
    func pathSeparatorsBecomeUnderscores(filename: String, expected: String) {
        #expect(safe(filename) == expected)
    }

    @Test func parentDirectoryTraversalStaysOneComponent() {
        #expect(safe("../../etc/passwd") == "_.._etc_passwd")
    }

    @Test(arguments: [".env", "...env", " .env "])
    func leadingDotsAndSpacesAreDropped(filename: String) {
        #expect(safe(filename) == "env")
    }

    @Test func controlCharactersBecomeUnderscores() {
        #expect(safe("a\u{0}b\nc") == "a_b_c")
    }

    @Test(arguments: ["", "   ", "...", ". ."])
    func emptyNameUsesTheFallback(filename: String) {
        #expect(safe(filename) == "at_000000000007")
    }
}
