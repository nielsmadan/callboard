import CallboardKit
import SwiftUI

struct FeedStatusView<Content: View>: View {
    let state: FeedState
    let store: String?
    let isEmpty: Bool
    let executablePath: String?
    let showsInstallHint: Bool
    @ViewBuilder let content: () -> Content

    var body: some View {
        switch state {
        case .starting:
            ProgressView("Connecting to callboard…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        case let .failed(message):
            failure(message)
        case .live, .reconnecting:
            feed
                .safeAreaInset(edge: .top, spacing: 0) {
                    if case let .reconnecting(message) = state {
                        reconnectingBar(message)
                    }
                }
        }
    }

    @ViewBuilder
    private var feed: some View {
        if !isEmpty {
            content()
        } else if let store {
            ContentUnavailableView {
                Label("No chats yet", systemImage: "bubble.left.and.bubble.right")
            } description: {
                Text(verbatim: store)
                    .textSelection(.enabled)
            }
        } else {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func reconnectingBar(_ message: String) -> some View {
        Label {
            Text(verbatim: message)
                .lineLimit(2)
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill")
        }
        .font(.callout)
        .foregroundStyle(.black)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(.yellow)
    }

    private func failure(_ message: String) -> some View {
        ContentUnavailableView {
            Label("Callboard is unavailable", systemImage: "exclamationmark.bubble")
        } description: {
            VStack(spacing: 8) {
                Text(verbatim: message)
                if showsInstallHint {
                    if let executablePath {
                        Text("Tried \(executablePath).")
                    }
                    Text("Install with `just install-editable` or choose it in Settings.")
                }
            }
            .textSelection(.enabled)
        } actions: {
            Button("Open Settings…") {
                WindowManager.shared.openSettings()
            }
        }
    }
}
