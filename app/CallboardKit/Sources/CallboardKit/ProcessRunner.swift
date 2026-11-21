import Foundation
import Synchronization

struct ProcessOutput: Sendable, Equatable {
    let stdout: Data
    let stderr: Data
    let exitCode: Int32
    let diedBySignal: Bool
}

enum ProcessRunner {
    static let maxStdoutBytes = 64 * 1024 * 1024
    static let killGrace = Duration.seconds(1)

    static func run(
        _ command: CallboardCommand,
        arguments: [String],
        name: String,
        timeout: Duration
    ) async throws -> ProcessOutput {
        let execution = Execution(command: command, arguments: arguments, name: name)
        let watchdog = Task {
            try await Task.sleep(for: timeout)
            execution.fail(CallboardError.timedOut(command: name))
        }
        defer { watchdog.cancel() }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                execution.start(continuation)
            }
        } onCancel: {
            execution.fail(CancellationError())
        }
    }
}

private final class Execution: Sendable {
    private struct State {
        var stdout = Data()
        var stderr = Data()
        var stdoutOpen = true
        var stderrOpen = true
        var running = true
        var exitCode: Int32 = 0
        var diedBySignal = false
        var failure: (any Error)?
        var continuation: CheckedContinuation<ProcessOutput, any Error>?
        var launched = false
    }

    private let state = Mutex(State())
    private let process = Process()
    private let stdoutPipe = Pipe()
    private let stderrPipe = Pipe()
    private let name: String

    init(command: CallboardCommand, arguments: [String], name: String) {
        self.name = name
        process.executableURL = command.executable
        process.arguments = arguments
        process.environment = command.processEnvironment
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
    }

    func start(_ continuation: CheckedContinuation<ProcessOutput, any Error>) {
        let pending = state.withLock { state -> (any Error)? in
            state.continuation = continuation
            return state.failure
        }
        if let pending {
            conclude(.failure(pending))
            return
        }
        process.terminationHandler = { [self] finished in
            terminated(finished.terminationStatus, bySignal: finished.terminationReason == .uncaughtSignal)
        }
        stdoutPipe.fileHandleForReading.readabilityHandler = { [self] handle in
            receive(handle.availableData, isStdout: true)
        }
        stderrPipe.fileHandleForReading.readabilityHandler = { [self] handle in
            receive(handle.availableData, isStdout: false)
        }
        do {
            try process.run()
        } catch {
            stopReading()
            conclude(.failure(CallboardError.launching(process.executableURL, failedWith: error)))
            return
        }
        let failedWhileLaunching = state.withLock { state -> Bool in
            state.launched = true
            return state.failure != nil
        }
        if failedWhileLaunching { stopProcess() }
    }

    func fail(_ error: any Error) {
        let shouldStop = state.withLock { state -> Bool in
            guard state.failure == nil else { return false }
            state.failure = error
            return state.launched && state.running
        }
        stopReading()
        if shouldStop {
            stopProcess()
        } else {
            finishIfDone()
        }
    }

    private func stopProcess() {
        process.terminate()
        let pid = process.processIdentifier
        Task {
            try? await Task.sleep(for: ProcessRunner.killGrace)
            if state.withLock({ $0.running }) { kill(pid, SIGKILL) }
        }
    }

    private func receive(_ data: Data, isStdout: Bool) {
        let overflow = state.withLock { state -> Bool in
            guard state.failure == nil else { return false }
            if data.isEmpty {
                if isStdout { state.stdoutOpen = false } else { state.stderrOpen = false }
                return false
            }
            if isStdout {
                state.stdout.append(data)
                return state.stdout.count > ProcessRunner.maxStdoutBytes
            }
            StandardError.append(data, to: &state.stderr)
            return false
        }
        if data.isEmpty { (isStdout ? stdoutPipe : stderrPipe).fileHandleForReading.readabilityHandler = nil }
        if overflow {
            fail(CallboardError.malformedOutput(
                command: name,
                detail: "stdout is larger than \(ProcessRunner.maxStdoutBytes >> 20) MB"
            ))
        }
        finishIfDone()
    }

    private func terminated(_ status: Int32, bySignal: Bool) {
        state.withLock {
            $0.running = false
            $0.exitCode = status
            $0.diedBySignal = bySignal
        }
        finishIfDone()
    }

    private func finishIfDone() {
        let outcome = state.withLock { state -> Result<ProcessOutput, any Error>? in
            guard !state.running, state.failure != nil || (!state.stdoutOpen && !state.stderrOpen) else {
                return nil
            }
            if let failure = state.failure { return .failure(failure) }
            return .success(ProcessOutput(
                stdout: state.stdout,
                stderr: state.stderr,
                exitCode: state.exitCode,
                diedBySignal: state.diedBySignal
            ))
        }
        guard let outcome else { return }
        stopReading()
        conclude(outcome)
    }

    private func conclude(_ outcome: Result<ProcessOutput, any Error>) {
        let continuation = state.withLock { state -> CheckedContinuation<ProcessOutput, any Error>? in
            defer { state.continuation = nil }
            return state.continuation
        }
        continuation?.resume(with: outcome)
    }

    private func stopReading() {
        for pipe in [stdoutPipe, stderrPipe] {
            pipe.fileHandleForReading.readabilityHandler = nil
        }
    }
}

enum StandardError {
    static let maxBytes = 64 * 1024

    static func append(_ data: Data, to buffer: inout Data) {
        buffer.append(data)
        if buffer.count > maxBytes { buffer = Data(buffer.suffix(maxBytes)) }
    }

    static func tail(of buffer: Data) -> String {
        // swiftlint:disable:next optional_data_string_conversion
        let text = String(decoding: buffer, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return String(text.suffix(500))
    }
}

extension CallboardCommand {
    var processEnvironment: [String: String] {
        ProcessInfo.processInfo.environment.merging(environment) { $1 }
    }
}

extension CallboardError {
    static func launching(_ executable: URL?, failedWith error: any Error) -> CallboardError {
        let path = executable?.path ?? ""
        let code = (error as NSError).code
        if code == NSFileNoSuchFileError || code == NSFileReadNoSuchFileError {
            return .executableNotFound(searched: [path])
        }
        return .launchFailed(path: path, reason: error.localizedDescription)
    }
}
