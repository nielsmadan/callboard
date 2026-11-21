import CallboardKit
import SwiftUI

struct MessageView: View {
    let message: ChatMessage
    let quote: ReplyQuote?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(verbatim: message.sender)
                    .font(.headline)
                Text(message.createdAt, format: .dateTime.month(.abbreviated).day().hour().minute())
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let quote {
                quoteView(quote)
            }
            Text(RenderedBodies.rendered(message))
                .environment(\.openURL, OpenURLAction { OpenPolicy.isLinkAllowed($0) ? .systemAction : .discarded })
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
            if message.bodyTruncated {
                Text("message truncated (open with `callboard admin history`)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            ForEach(message.attachments) { attachment in
                attachmentButton(attachment)
            }
        }
    }

    private func quoteView(_ quote: ReplyQuote) -> some View {
        Group {
            switch quote {
            case let .parent(sender, line):
                Text(verbatim: "\(sender): \(line)")
            case let .unloaded(parentId):
                Text(verbatim: "reply to \(parentId)")
            }
        }
        .font(.callout)
        .foregroundStyle(.secondary)
        .lineLimit(1)
        .padding(.leading, 8)
        .overlay(alignment: .leading) {
            Rectangle()
                .fill(.tertiary)
                .frame(width: 2)
        }
    }

    private func displayName(_ attachment: AttachmentInfo) -> String {
        AttachmentNaming.safeFilename(attachment.filename, fallback: attachment.id)
    }

    private func attachmentButton(_ attachment: AttachmentInfo) -> some View {
        Button {
            AttachmentOpener.open(attachment)
        } label: {
            Label {
                Text(verbatim: "\(displayName(attachment)) (\(attachment.size.formatted(.byteCount(style: .file))))")
            } icon: {
                Image(systemName: "paperclip")
            }
        }
        .buttonStyle(.link)
        .help(attachment.mediaType)
        .contextMenu {
            Button("Save As…") {
                AttachmentOpener.saveAs(attachment)
            }
        }
    }
}

@MainActor
private enum RenderedBodies {
    private final class Box {
        let value: AttributedString
        init(_ value: AttributedString) { self.value = value }
    }

    private static let cache: NSCache<NSString, Box> = {
        let cache = NSCache<NSString, Box>()
        cache.countLimit = 2000
        return cache
    }()

    static func rendered(_ message: ChatMessage) -> AttributedString {
        let key = message.id as NSString
        if let hit = cache.object(forKey: key) { return hit.value }
        let value = MessageMarkdown.render(message.body)
        cache.setObject(Box(value), forKey: key)
        return value
    }
}
