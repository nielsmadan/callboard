import CallboardKit
import Foundation
import Observation

private extension FeedConfiguration {
    init(defaults: UserDefaults) {
        self.init(
            callboardPath: defaults.string(forKey: AppStorageKeys.callboardPath),
            storeFolder: defaults.string(forKey: AppStorageKeys.storeFolder),
            home: FileManager.default.homeDirectoryForCurrentUser.path
        )
    }
}

@MainActor @Observable
final class AppModel {
    static let shared = AppModel()

    private(set) var chats: ChatStore?
    private(set) var executable: Resolution?
    private var configurationProblem: CallboardError?
    var isViewing = false {
        didSet { chats?.isViewing = isViewing }
    }

    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let tracker: LocalViewTracker
    @ObservationIgnored private var configuration: FeedConfiguration?
    @ObservationIgnored private var feed: Task<Void, Never>?

    private init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        tracker = LocalViewTracker(defaults: defaults, key: AppStorageKeys.viewMarks)
    }

    var feedState: FeedState {
        if let configurationProblem {
            return .failed(configurationProblem.localizedDescription)
        }
        if case let .notFound(searched) = executable {
            return .failed(CallboardError.executableNotFound(searched: searched).localizedDescription)
        }
        return chats?.state ?? .starting
    }

    var showsInstallHint: Bool {
        configurationProblem?.pointsToExecutable ?? true
    }

    var executablePath: String? {
        guard case let .found(url) = executable else { return nil }
        return url.path
    }

    func start() {
        _ = NotificationCenter.default.addObserver(
            forName: UserDefaults.didChangeNotification,
            object: defaults,
            queue: .main
        ) { _ in
            MainActor.assumeIsolated { AppModel.shared.applyConfiguration() }
        }
        applyConfiguration()
    }

    private func applyConfiguration() {
        let next = FeedConfiguration(defaults: defaults)
        guard next != configuration else { return }
        configuration = next
        report(Self.resolve(next))
        configurationProblem = next.problem
        let previous = feed
        previous?.cancel()
        feed = Task {
            await previous?.value
            guard !Task.isCancelled else { return }
            await run(next)
        }
    }

    private static func resolve(_ configuration: FeedConfiguration) -> Resolution {
        let fileManager = FileManager.default
        return ExecutableLocator.resolve(
            override: configuration.callboardPath,
            home: fileManager.homeDirectoryForCurrentUser,
            isExecutable: fileManager.isExecutableFile(atPath:)
        )
    }

    private func report(_ resolution: Resolution) {
        guard resolution != executable else { return }
        executable = resolution
        if case .notFound = resolution {
            chats = nil
            LogManager.log(.error, .feed, feedState.message ?? "callboard was not found")
        }
    }

    private func run(_ configuration: FeedConfiguration) async {
        if let problem = configuration.problem {
            chats = nil
            LogManager.log(.error, .feed, problem.localizedDescription)
            return
        }
        guard let url = await ExecutableLocator.awaitExecutable(
            every: .seconds(5),
            resolve: { Self.resolve(configuration) },
            report: { self.report($0) }
        ) else { return }
        let command = CallboardCommand(executable: url, environment: configuration.environment)
        let store = ChatStore(
            reader: CallboardClient(command: command),
            source: CallboardWatch(command: command),
            tracker: tracker
        )
        store.isViewing = isViewing
        chats = store
        LogManager.log(.info, .feed, "watching with \(url.path)")
        await store.run()
    }
}

extension FeedState {
    var message: String? {
        switch self {
        case .starting, .live: nil
        case let .reconnecting(message), let .failed(message): message
        }
    }
}
