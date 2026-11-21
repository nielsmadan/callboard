import CallboardKit
import SwiftUI

struct ConversationDetailView: View {
    let conversation: ConversationSummary
    let thread: ThreadState
    let loadOlder: () -> Void
    let retry: () -> Void

    @State private var position = ScrollPosition(edge: .bottom)
    @State private var isAtBottom = true

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            messages
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(verbatim: ListArrangement.title(of: conversation))
                .font(.title3.bold())
            Text(verbatim: subtitle)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
    }

    private var subtitle: String {
        let members = conversation.members.joined(separator: ", ")
        return conversation.project.map { "\(members) · \($0)" } ?? members
    }

    private var messages: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 14) {
                if thread.more, !thread.messages.isEmpty {
                    Button("Load Older Messages", action: loadOlder)
                        .disabled(thread.loading)
                        .frame(maxWidth: .infinity)
                }
                if let error = thread.error {
                    Text(verbatim: error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                    if thread.messages.isEmpty {
                        Button("Try Again", action: retry)
                    }
                }
                ForEach(thread.messages) { message in
                    MessageView(message: message, quote: Formatting.replyQuote(for: message, in: thread.messages))
                }
            }
            .padding(16)
        }
        .defaultScrollAnchor(.bottom)
        .scrollPosition($position)
        .onScrollGeometryChange(for: Bool.self) { geometry in
            geometry.visibleRect.maxY >= geometry.contentSize.height - 24
        } action: { _, atBottom in
            isAtBottom = atBottom
        }
        .onChange(of: thread.messages.last?.id) {
            if isAtBottom {
                position.scrollTo(edge: .bottom)
            }
        }
        .overlay {
            if thread.loading, thread.messages.isEmpty {
                ProgressView()
            }
        }
    }
}
