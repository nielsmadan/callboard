import CallboardKit
import Foundation
import Testing

@Suite("OpenPolicy")
struct OpenPolicyTests {
    @Test(arguments: ["https://example.com", "HTTP://example.com", "mailto:a@b.c"])
    func webAndMailLinksAreAllowed(link: String) throws {
        let url = try #require(URL(string: link))
        #expect(OpenPolicy.isLinkAllowed(url))
    }

    @Test(arguments: ["file:///Applications/Some.app", "x-custom://run", "ssh://host", "/relative/path"])
    func otherLinksAreRefused(link: String) throws {
        let url = try #require(URL(string: link))
        #expect(OpenPolicy.isLinkAllowed(url) == false)
    }

    @Test(arguments: ["notes.txt", "photo.PNG", "report.pdf", "README", "data.json"])
    func documentsOpenDirectly(filename: String) {
        #expect(OpenPolicy.isSafeToOpen(filename: filename))
    }

    @Test(arguments: ["report.terminal", "fix.zip", "run.sh", "tool.jar", "x.command", "Some.app", "FIX.ZIP"])
    func executableAndArchiveTypesAreRevealedInstead(filename: String) {
        #expect(OpenPolicy.isSafeToOpen(filename: filename) == false)
    }

    @Test(arguments: ["home.inetloc", "disk.fileloc", "site.url", "wifi.mobileconfig", "run.shortcut", "app.jnlp"])
    func shortcutAndProfileFilesAreRevealedInstead(filename: String) {
        #expect(OpenPolicy.isSafeToOpen(filename: filename) == false)
    }

    @Test func markdownLinksAndEmphasisAreParsed() {
        let rendered = MessageMarkdown.render("see **this** [site](https://example.com)")
        #expect(String(rendered.characters) == "see this site")
        #expect(rendered.runs.contains { $0.link == URL(string: "https://example.com") })
    }
}
