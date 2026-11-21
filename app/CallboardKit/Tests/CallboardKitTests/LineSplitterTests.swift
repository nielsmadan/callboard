@testable import CallboardKit
import Foundation
import Testing

@Suite("LineSplitter")
struct LineSplitterTests {
    struct Case: Sendable, CustomTestStringConvertible {
        let chunks: [String]
        let pieces: [String]

        var testDescription: String {
            chunks.debugDescription
        }
    }

    private static let cases: [Case] = [
        Case(chunks: ["abc\n"], pieces: ["abc"]),
        Case(chunks: ["a\nbb\nccc\n"], pieces: ["a", "bb", "ccc"]),
        Case(chunks: ["ab", "c\nd", "e\n"], pieces: ["abc", "de"]),
        Case(chunks: ["abc", "\n"], pieces: ["abc"]),
        Case(chunks: ["\n\na\n"], pieces: ["a"]),
        Case(chunks: ["abc"], pieces: ["abc"]),
        Case(chunks: ["a\nbc"], pieces: ["a", "bc"]),
        Case(chunks: ["12345678\n"], pieces: ["12345678"]),
        Case(chunks: ["123456789\nok\n"], pieces: ["<overflow>", "ok"]),
        Case(chunks: ["12345", "6789", "abc\nok\n"], pieces: ["<overflow>", "ok"]),
        Case(chunks: ["123456789"], pieces: ["<overflow>"]),
        Case(chunks: ["123456789\n123456789\n"], pieces: ["<overflow>", "<overflow>"])
    ]

    @Test(arguments: cases)
    func splitsChunksIntoLines(_ example: Case) {
        var splitter = LineSplitter(limit: 8)
        let pieces = example.chunks.flatMap { splitter.feed(Data($0.utf8)) } + splitter.flush()
        #expect(pieces.map(Self.describe) == example.pieces)
    }

    @Test func flushingTwiceYieldsTheTailOnce() {
        var splitter = LineSplitter(limit: 8)
        _ = splitter.feed(Data("tail".utf8))
        #expect(splitter.flush() == [.line(Data("tail".utf8))])
        #expect(splitter.flush().isEmpty)
    }

    private static func describe(_ piece: LineSplitter.Piece) -> String {
        switch piece {
        case let .line(data): String(decoding: data, as: UTF8.self)
        case .overflow: "<overflow>"
        }
    }
}
