import Foundation
import Synchronization

public protocol EventSource: Sendable {
    func events() -> AsyncThrowingStream<WatchEvent, Error>
}

public struct CallboardWatch: EventSource {
    static let maxLineBytes = 64 * 1024 * 1024

    private let command: CallboardCommand
    private let interval: Double

    public init(command: CallboardCommand, interval: Double = 0.25) {
        self.command = command
        self.interval = interval
    }

    public func events() -> AsyncThrowingStream<WatchEvent, Error> {
        let (stream, continuation) = AsyncThrowingStream.makeStream(
            of: WatchEvent.self,
            throwing: Error.self,
            bufferingPolicy: .unbounded
        )
        let session = WatchSession(
            command: command,
            arguments: ["admin", "watch", "--json", "--interval", String(interval)],
            lineLimit: Self.maxLineBytes,
            continuation: continuation
        )
        continuation.onTermination = { termination in
            if case .cancelled = termination { session.cancel() } else { session.stop() }
        }
        session.start()
        return stream
    }
}

private struct WireEvent: Decodable {
    let event: WatchEvent?

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: Key.self)
        let kind = try container.decode(String.self, forKey: .event)
        switch kind {
        case "snapshot":
            event = try .snapshot(Snapshot(from: decoder))
        case "messages":
            event = try .messages(MessageBatch(from: decoder))
        default:
            event = nil
        }
    }

    private enum Key: String, CodingKey {
        case event
    }
}

private final class WatchSession: Sendable {
    private static let name = "admin watch"
    private static let lifelineGrace = Duration.seconds(2)
    private static let killGrace = Duration.seconds(1)
    private static let quietPeriod = Duration.seconds(1)
    private static let drainCap = Duration.seconds(5)

    private enum Failure: Error {
        case thrown(any Error)
        case reported(code: String?, message: String)
    }

    private struct State {
        var splitter: LineSplitter
        var standardError = Data()
        var launched = false
        var exited = false
        var exitCode: Int32 = 0
        var stdoutOpen = true
        var stderrOpen = true
        var reads = 0
        var failure: Failure?
        var stopping = false
        var cancelled = false
        var concluded = false

        var accepting: Bool {
            !concluded && !cancelled && failure == nil
        }
    }

    private let state: Mutex<State>
    private let process = Process()
    private let stdinPipe = Pipe()
    private let stdoutPipe = Pipe()
    private let stderrPipe = Pipe()
    private let continuation: AsyncThrowingStream<WatchEvent, Error>.Continuation

    init(
        command: CallboardCommand,
        arguments: [String],
        lineLimit: Int,
        continuation: AsyncThrowingStream<WatchEvent, Error>.Continuation
    ) {
        state = Mutex(State(splitter: LineSplitter(limit: lineLimit)))
        self.continuation = continuation
        process.executableURL = command.executable
        process.arguments = arguments
        process.environment = command.processEnvironment
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
    }

    func start() {
        process.terminationHandler = { [self] finished in
            exited(finished.terminationStatus)
        }
        stdoutPipe.fileHandleForReading.readabilityHandler = { [self] handle in
            receiveOutput(handle.availableData)
        }
        stderrPipe.fileHandleForReading.readabilityHandler = { [self] handle in
            receiveError(handle.availableData)
        }
        do {
            try process.run()
        } catch {
            let failure = CallboardError.launching(process.executableURL, failedWith: error)
            state.withLock {
                $0.failure = .thrown(failure)
                $0.exited = true
                $0.stdoutOpen = false
                $0.stderrOpen = false
            }
            concludeIfDone()
            return
        }
        try? stdinPipe.fileHandleForReading.close()
        let stoppedWhileLaunching = state.withLock { state -> Bool in
            state.launched = true
            return state.stopping && !state.exited
        }
        if stoppedWhileLaunching { escalate() }
    }

    func cancel() {
        state.withLock { $0.cancelled = true }
        stop()
    }

    func stop() {
        let (first, running) = state.withLock { state -> (Bool, Bool) in
            defer { state.stopping = true }
            return (!state.stopping, state.launched && !state.exited)
        }
        guard first else { return }
        try? stdinPipe.fileHandleForWriting.close()
        if running { escalate() }
    }

    private func escalate() {
        let pid = process.processIdentifier
        Task {
            try? await Task.sleep(for: Self.lifelineGrace)
            guard isRunning else { return }
            kill(pid, SIGTERM)
            try? await Task.sleep(for: Self.killGrace)
            guard isRunning else { return }
            kill(pid, SIGKILL)
        }
    }

    private var isRunning: Bool {
        state.withLock { !$0.exited }
    }

    private func receiveOutput(_ data: Data) {
        if data.isEmpty { stdoutPipe.fileHandleForReading.readabilityHandler = nil }
        let failed = state.withLock { state -> Bool in
            state.reads += 1
            guard !data.isEmpty else {
                state.stdoutOpen = false
                return false
            }
            guard state.accepting else { return false }
            return deliver(state.splitter.feed(data), into: &state)
        }
        if failed { stop() }
        concludeIfDone()
    }

    private func receiveError(_ data: Data) {
        if data.isEmpty { stderrPipe.fileHandleForReading.readabilityHandler = nil }
        state.withLock { state in
            state.reads += 1
            if data.isEmpty {
                state.stderrOpen = false
            } else {
                StandardError.append(data, to: &state.standardError)
            }
        }
        concludeIfDone()
    }

    private func deliver(_ pieces: [LineSplitter.Piece], into state: inout State) -> Bool {
        guard state.accepting else { return false }
        for piece in pieces {
            switch event(from: piece) {
            case let .success(event):
                if let event { continuation.yield(event) }
            case let .failure(failure):
                state.failure = failure
                return true
            }
        }
        return false
    }

    private func event(from piece: LineSplitter.Piece) -> Result<WatchEvent?, Failure> {
        guard case let .line(line) = piece else {
            return .failure(.thrown(CallboardError.malformedOutput(
                command: Self.name,
                detail: "a line is longer than \(CallboardWatch.maxLineBytes >> 20) MB"
            )))
        }
        do {
            switch try Envelope.reply(WireEvent.self, from: line, command: Self.name) {
            case let .ok(wire):
                return .success(wire.event)
            case let .failed(code, message):
                return .failure(.reported(code: code, message: message))
            case nil:
                return .failure(.thrown(CallboardError.malformedOutput(
                    command: Self.name,
                    detail: "a line is not a callboard envelope"
                )))
            }
        } catch {
            return .failure(.thrown(error))
        }
    }

    private func exited(_ status: Int32) {
        state.withLock {
            $0.exited = true
            $0.exitCode = status
        }
        concludeIfDone()
        Task { await concludeOnceQuiet() }
    }

    private func concludeOnceQuiet() async {
        var reads = state.withLock { $0.reads }
        let deadline = ContinuousClock.now + Self.drainCap
        while ContinuousClock.now < deadline {
            try? await Task.sleep(for: Self.quietPeriod)
            let (concluded, now) = state.withLock { ($0.concluded, $0.reads) }
            if concluded { return }
            if now == reads { break }
            reads = now
        }
        concludeIfDone(force: true)
    }

    private func concludeIfDone(force: Bool = false) {
        let ending = state.withLock { state -> (any Error)? in
            guard !state.concluded, state.exited, force || (!state.stdoutOpen && !state.stderrOpen) else {
                return nil
            }
            _ = deliver(state.splitter.flush(), into: &state)
            state.concluded = true
            return ending(of: state)
        }
        guard let ending else { return }
        stopReading()
        continuation.finish(throwing: ending)
    }

    private func ending(of state: State) -> any Error {
        switch state.failure {
        case let .thrown(error):
            error
        case let .reported(code, message):
            CallboardError.commandFailed(command: Self.name, exitCode: state.exitCode, code: code, message: message)
        case nil:
            CallboardError.streamEnded(
                exitCode: state.exitCode,
                standardError: StandardError.tail(of: state.standardError)
            )
        }
    }

    private func stopReading() {
        stdoutPipe.fileHandleForReading.readabilityHandler = nil
        stderrPipe.fileHandleForReading.readabilityHandler = nil
        process.terminationHandler = nil
    }
}
