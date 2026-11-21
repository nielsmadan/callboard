import CallboardKit
import Foundation
import Testing

@Suite("WatchEvent")
struct WatchEventTests {
    private func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }

    @Test func eventsCompareByTheirPayload() throws {
        let snapshot = try decoder().decode(Snapshot.self, from: Fixture.data("admin-conversations"))
        let empty = try decoder().decode(
            Snapshot.self,
            from: Data(#"{"store": "s", "cursor": 0, "conversations": []}"#.utf8)
        )
        let batch = try decoder().decode(
            MessageBatch.self,
            from: Data(#"{"cursor": 3, "messages": [], "conversations": []}"#.utf8)
        )
        #expect(WatchEvent.snapshot(snapshot) == .snapshot(snapshot))
        #expect(WatchEvent.snapshot(snapshot) != .snapshot(empty))
        #expect(WatchEvent.messages(batch) != .snapshot(snapshot))
    }
}
