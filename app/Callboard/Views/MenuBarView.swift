import CallboardKit
import SwiftUI

extension AppSection {
    var symbol: String {
        switch self {
        case .chats: "bubble.left.and.bubble.right"
        }
    }

    @MainActor
    func newCount(in model: AppModel) -> Int {
        switch self {
        case .chats: model.chats?.totalNew ?? 0
        }
    }
}

struct MenuBarView: View {
    @Environment(AppModel.self) private var model
    let onOpen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(AppSection.allCases, id: \.self) { section in
                sectionRow(section)
            }
            Divider()
            Text(verbatim: footer)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .help(footer)
                .padding(.horizontal, 8)
        }
        .padding(8)
        .frame(width: 260)
    }

    private func sectionRow(_ section: AppSection) -> some View {
        let count = section.newCount(in: model)
        return Button {
            WindowManager.shared.openMainWindow()
            onOpen()
        } label: {
            HStack {
                Label(section.title, systemImage: section.symbol)
                Spacer()
                if count > 0 {
                    Text(verbatim: BadgeText.title(count))
                        .font(.caption.bold())
                        .monospacedDigit()
                        .foregroundStyle(.white)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 1)
                        .background(Capsule().fill(.red))
                }
            }
            .contentShape(Rectangle())
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(verbatim: "\(section.title), \(count) new"))
    }

    private var footer: String {
        switch model.feedState {
        case .starting: "Connecting…"
        case .live: "Connected"
        case let .reconnecting(message), let .failed(message): message
        }
    }
}
