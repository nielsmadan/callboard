import CallboardKit
import SwiftUI

struct ConversationListView: View {
    let sections: [RowSection]
    let mode: ListMode
    @Binding var selection: String?

    var body: some View {
        ScrollViewReader { proxy in
            List(selection: $selection) {
                ForEach(sections) { section in
                    if let title = section.title {
                        Section(title) {
                            rows(of: section)
                        }
                    } else {
                        rows(of: section)
                    }
                }
            }
            .listStyle(.sidebar)
            .onChange(of: selection) { _, id in
                if let id {
                    proxy.scrollTo(id)
                }
            }
        }
    }

    private func rows(of section: RowSection) -> some View {
        ForEach(section.rows) { row in
            ConversationRowView(row: row, mode: mode)
        }
    }
}
