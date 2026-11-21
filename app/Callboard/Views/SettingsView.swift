import AppKit
import CallboardKit
import ShortcutKit
import ShortcutKitUI
import SwiftUI

struct SettingsView: View {
    var body: some View {
        TabView {
            GeneralSettingsView()
                .tabItem { Label("General", systemImage: "gear") }
            ShortcutsSettingsView()
                .tabItem { Label("Shortcuts", systemImage: "keyboard") }
        }
        .frame(width: 560, height: 420)
    }
}

struct GeneralSettingsView: View {
    @Environment(AppModel.self) private var model
    @AppStorage(AppStorageKeys.listMode) private var listMode: ListMode = .grouped
    @AppStorage(AppStorageKeys.callboardPath) private var callboardPath = ""
    @AppStorage(AppStorageKeys.storeFolder) private var storeFolder = ""
    @State private var pathDraft = ""
    @State private var folderDraft = ""
    @FocusState private var focus: Field?

    private enum Field { case path, folder }

    var body: some View {
        Form {
            Picker("List mode", selection: $listMode) {
                Text("Groups and direct messages").tag(ListMode.grouped)
                Text("Most recent first").tag(ListMode.recent)
            }
            Section("callboard executable") {
                HStack {
                    TextField("Path", text: $pathDraft, prompt: Text("Automatic"))
                        .focused($focus, equals: .path)
                        .onSubmit { callboardPath = pathDraft }
                    Button("Choose…") { chooseExecutable() }
                }
                Text(verbatim: resolvedText)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            Section("Store folder (XDG_DATA_HOME)") {
                HStack {
                    TextField("Folder", text: $folderDraft, prompt: Text("Default"))
                        .focused($focus, equals: .folder)
                        .onSubmit { storeFolder = folderDraft }
                    Button("Choose…") { chooseFolder() }
                    Button("Use default") {
                        storeFolder = ""
                        folderDraft = ""
                    }
                    .disabled(storeFolder.isEmpty)
                }
            }
        }
        .formStyle(.grouped)
        .onAppear {
            pathDraft = callboardPath
            folderDraft = storeFolder
        }
        .onDisappear {
            callboardPath = pathDraft
            storeFolder = folderDraft
        }
        .onChange(of: focus) { previous, _ in
            switch previous {
            case .path: callboardPath = pathDraft
            case .folder: storeFolder = folderDraft
            case nil: break
            }
        }
    }

    private var resolvedText: String {
        model.executablePath.map { "Using \($0)" } ?? "callboard not found"
    }

    private func chooseExecutable() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.treatsFilePackagesAsDirectories = true
        panel.showsHiddenFiles = true
        if panel.runModal() == .OK, let url = panel.url {
            callboardPath = url.path
            pathDraft = url.path
        }
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            storeFolder = url.path
            folderDraft = url.path
        }
    }
}

struct ShortcutsSettingsView: View {
    var body: some View {
        Form {
            Section("Display") {
                HintPreferencesView(registry: ShortcutCenter.shared.registry)
            }
            KeyBindingsView(
                registry: ShortcutCenter.shared.registry,
                style: .regular,
                presentation: .embedded,
                showsDescriptions: true
            )
        }
        .formStyle(.grouped)
    }
}
