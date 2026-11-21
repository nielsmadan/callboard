import AppKit
import CallboardKit
import CoreServices

enum AttachmentOpener {
    private nonisolated static let cacheFolder = "com.nielsmadan.Callboard/attachments"

    static func open(_ attachment: AttachmentInfo) {
        Task {
            do {
                let copy = try await Task.detached { try cachedCopy(of: attachment) }.value
                if OpenPolicy.isSafeToOpen(filename: copy.lastPathComponent) {
                    NSWorkspace.shared.open(copy)
                } else {
                    NSWorkspace.shared.activateFileViewerSelecting([copy])
                }
            } catch {
                report(error, for: attachment)
            }
        }
    }

    static func saveAs(_ attachment: AttachmentInfo) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = filename(of: attachment)
        panel.begin { response in
            guard response == .OK, let destination = panel.url else { return }
            Task {
                do {
                    try await Task.detached {
                        try replace(destination, withCopyOf: URL(filePath: attachment.path))
                    }.value
                } catch {
                    report(error, for: attachment)
                }
            }
        }
    }

    private nonisolated static func filename(of attachment: AttachmentInfo) -> String {
        AttachmentNaming.safeFilename(attachment.filename, fallback: attachment.id)
    }

    private nonisolated static func cachedCopy(of attachment: AttachmentInfo) throws -> URL {
        let caches = try FileManager.default.url(
            for: .cachesDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let folder = caches
            .appending(path: cacheFolder, directoryHint: .isDirectory)
            .appending(
                path: AttachmentNaming.safeFilename(attachment.id, fallback: "attachment"),
                directoryHint: .isDirectory
            )
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let destination = folder.appending(path: filename(of: attachment), directoryHint: .notDirectory)
        try replace(destination, withCopyOf: URL(filePath: attachment.path))
        var values = URLResourceValues()
        values.quarantineProperties = [kLSQuarantineTypeKey as String: kLSQuarantineTypeOtherDownload as String]
        var quarantined = destination
        try quarantined.setResourceValues(values)
        return destination
    }

    private nonisolated static func replace(_ destination: URL, withCopyOf source: URL) throws {
        let manager = FileManager.default
        let staged = destination.deletingLastPathComponent().appending(path: ".\(UUID().uuidString).tmp")
        do {
            try manager.copyItem(at: source, to: staged)
            try manager.setAttributes([.posixPermissions: 0o644], ofItemAtPath: staged.path)
            if manager.fileExists(atPath: destination.path) {
                _ = try manager.replaceItemAt(destination, withItemAt: staged)
            } else {
                try manager.moveItem(at: staged, to: destination)
            }
        } catch {
            try? manager.removeItem(at: staged)
            throw error
        }
    }

    private static func report(_ error: any Error, for attachment: AttachmentInfo) {
        LogManager.log(.error, .ui, "attachment \(attachment.id) could not be copied: \(error.localizedDescription)")
        NSAlert(error: error).runModal()
    }
}
