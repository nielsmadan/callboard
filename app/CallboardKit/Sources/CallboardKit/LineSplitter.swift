import Foundation

struct LineSplitter {
    enum Piece: Equatable {
        case line(Data)
        case overflow
    }

    private let limit: Int
    private var partial = Data()
    private var discarding = false

    init(limit: Int) {
        self.limit = limit
    }

    mutating func feed(_ chunk: Data) -> [Piece] {
        var pieces: [Piece] = []
        var start = chunk.startIndex
        while let newline = chunk[start...].firstIndex(of: UInt8(ascii: "\n")) {
            pieces += take(chunk[start ..< newline], endsLine: true)
            start = chunk.index(after: newline)
        }
        return pieces + take(chunk[start...], endsLine: false)
    }

    mutating func flush() -> [Piece] {
        take(Data(), endsLine: true)
    }

    private mutating func take(_ segment: Data, endsLine: Bool) -> [Piece] {
        var pieces: [Piece] = []
        if !discarding, partial.count + segment.count > limit {
            discarding = true
            partial = Data()
            pieces.append(.overflow)
        } else if !discarding {
            partial.append(segment)
        }
        if endsLine {
            if !discarding, !partial.isEmpty { pieces.append(.line(partial)) }
            partial = Data()
            discarding = false
        }
        return pieces
    }
}
