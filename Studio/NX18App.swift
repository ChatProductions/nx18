import SwiftUI
import UniformTypeIdentifiers
import Foundation

@main
struct NX18App: App {
    var body: some Scene {
        WindowGroup {
            StudioView()
        }
    }


}

struct StudioView: View {
    @State private var localNSPs: [URL] = []
    @State private var inboxStatus = "Checking local NSP-Inbox…"
    @State private var busy = false
    @State private var status = "No NSP imported."
    @State private var report = ""
    @State private var inspectedURL: URL?
    @State private var inspectedIndex: NSPIndex?
    @State private var metalStatus = "Not tested on this device."
    @State private var switchKeys: SwitchKeys?
    @State private var keyStatus = "No header key imported."

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("nx18")
                        .font(.system(size: 38, weight: .bold, design: .rounded))
                    Text("Native Switch-to-iOS research studio")
                        .foregroundStyle(.secondary)
                    Text("Target: iPhone 13 • iOS 18 • Metal 3")
                        .font(.footnote.monospaced())
                        .foregroundStyle(.secondary)

                    GroupBox("Switch game inspection") {
                        VStack(alignment: .leading, spacing: 9) {
                            Text("First target: Terminator 2D: NO FATE")
                                .font(.headline)
                            Text("Terminator: 0100B51020B68000")
                                .font(.caption.monospaced())
                            Text("Import a base-game NSP, load your own prod.keys locally, then extract decrypted ExeFS modules for native ARM64 rewriting. This is not yet an on-device game launch.")
                                .font(.subheadline)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Button {
                        status = "Opening UIKit Files picker…"
                        NX18DocumentPicker.open(
                            didSelect: { url in inspect(url) },
                            didCancel: { status = "NSP selection cancelled." },
                            didFail: { reason in status = "Files picker: " + reason }
                        )
                    } label: {
                        Label("Choose NSP using Files", systemImage: "doc.text.magnifyingglass")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy)

                    GroupBox("NSP-Inbox: works without a file picker") {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Move your .nsp into Files → On My iPhone → nx18 → NSP-Inbox. Then tap Refresh below.")
                                .font(.footnote)
                            Button {
                                refreshNSPInbox()
                            } label: {
                                Label("Refresh NSP-Inbox", systemImage: "arrow.clockwise")
                            }
                            .buttonStyle(.bordered)
                            .disabled(busy)

                            if localNSPs.isEmpty {
                                Text(inboxStatus)
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                            } else {
                                ForEach(localNSPs, id: \.path) { game in
                                    Button {
                                        inspect(game)
                                    } label: {
                                        Label(game.lastPathComponent, systemImage: "shippingbox")
                                            .lineLimit(2)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                    .buttonStyle(.bordered)
                                    .disabled(busy)
                                }
                                Text(inboxStatus)
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    if busy {
                        ProgressView("Processing on this iPhone…")
                    }

                    if inspectedIndex != nil {
                        Button {
                            extractInspected()
                        } label: {
                            Label("Extract encrypted NSP files", systemImage: "archivebox")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .disabled(busy)
                        Text("Copies NCA and ticket files to Documents/nx18-extracted. This uses additional free storage and does not decrypt them.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)

                        Button {
                            keyStatus = "Opening native Files picker for your key file…"
                            NX18DocumentPicker.open(
                                didSelect: { url in loadKeys(url) },
                                didCancel: { keyStatus = "Key selection cancelled." },
                                didFail: { reason in keyStatus = "Key picker: " + reason }
                            )
                        } label: {
                            Label("Load prod.keys locally", systemImage: "key")
                        }
                        .buttonStyle(.bordered)
                        .disabled(busy)

                        Text(keyStatus)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        if switchKeys != nil {
                            Button("Identify encrypted NCA titles") { inspectNCAHeaders() }
                                .buttonStyle(.bordered)
                                .disabled(busy)

                            Button {
                                exportExeFS()
                            } label: {
                                Label("Decrypt and extract ExeFS", systemImage: "cpu")
                                    .frame(maxWidth: .infinity)
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(busy)
                        }
                        Text("Keys stay in memory. Supported NCA3 base-game Program archives yield native Switch NSO files; updates, RomFS extraction and native iOS game execution are separate stages.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }

                    Text(status)
                        .foregroundStyle(.secondary)
                        .font(.subheadline)

                    if !report.isEmpty {
                        GroupBox("Local inspection report") {
                            Text(report)
                                .font(.system(.caption, design: .monospaced))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        ShareLink(item: report) {
                            Label("Share diagnostic report", systemImage: "square.and.arrow.up")
                        }
                    }

                    GroupBox("Metal 3 runtime check") {
                        VStack(alignment: .leading, spacing: 10) {
                            Button("Compile and render Metal shader on-device") {
                                probeMetal()
                            }
                            .buttonStyle(.bordered)
                            .disabled(busy)
                            Text(metalStatus)
                                .font(.footnote)
                                .textSelection(.enabled)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    GroupBox("Porting status") {
                        VStack(alignment: .leading, spacing: 6) {
                            Label("PFS0 extraction + NCA header identification: implemented", systemImage: "checkmark.circle")
                            Label("Base-game NCA3 ExeFS extraction: implemented (test-stage)", systemImage: "checkmark.circle")
                            Label("RomFS and update-layer decryption: not implemented", systemImage: "circle.dashed")
                            Label("ARM64 static rewriting: not implemented", systemImage: "circle.dashed")
                            Label("Metal 3 renderer / A15 texture fallback: not implemented", systemImage: "circle.dashed")
                            Label("Playable unsigned IPA export: not implemented", systemImage: "circle.dashed")
                        }
                        .font(.footnote)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Text("No Switch files or keys leave your device. This build does not execute Switch games.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .padding(20)
            }
            .navigationBarTitleDisplayMode(.inline)
            .onAppear { refreshNSPInbox() }
        }
    }

    private func refreshNSPInbox() {
        let manager = FileManager.default
        let documents = manager.urls(for: .documentDirectory,
                                      in: .userDomainMask)[0]
        let inbox = documents.appendingPathComponent("NSP-Inbox", isDirectory: true)
        do {
            try manager.createDirectory(at: inbox, withIntermediateDirectories: true)
            let guide = inbox.appendingPathComponent("PUT_NSP_FILES_HERE.txt")
            if !manager.fileExists(atPath: guide.path) {
                try "Move your own base-game .nsp here, then open NX18 and tap Refresh NSP-Inbox.\nNo RomFS extraction is needed just to select the NSP.\n"
                    .write(to: guide, atomically: true, encoding: .utf8)
            }
            // Allow files in the app's Documents root, too. No game archive
            // needs to be opened via a system file picker.
            let possible = [inbox, documents]
            var found: [URL] = []
            for directory in possible {
                let contents = try manager.contentsOfDirectory(at: directory,
                    includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey],
                    options: [.skipsHiddenFiles])
                for url in contents where url.pathExtension.lowercased() == "nsp" {
                    let resource = try url.resourceValues(
                        forKeys: [.isRegularFileKey, .fileSizeKey])
                    if resource.isRegularFile == true &&
                       (resource.fileSize ?? 0) >= 16 {
                        found.append(url)
                    }
                }
            }
            localNSPs = found.sorted { $0.lastPathComponent.localizedStandardCompare(
                $1.lastPathComponent) == .orderedAscending }
            inboxStatus = localNSPs.isEmpty
                ? "No .nsp found yet. Copy it into the NSP-Inbox in Files, then refresh."
                : "Found \(localNSPs.count) local NSP file(s). Tap one to inspect it."
        } catch {
            localNSPs = []
            inboxStatus = "Cannot access NSP-Inbox: " + error.localizedDescription
        }
    }

    private func inspect(_ url: URL) {
        busy = true
        report = ""
        inspectedIndex = nil
        inspectedURL = nil
        status = "Inspecting " + url.lastPathComponent + "…"
        Task.detached(priority: .userInitiated) {
            let scoped = url.startAccessingSecurityScopedResource()
            defer {
                if scoped { url.stopAccessingSecurityScopedResource() }
            }
            do {
                let index = try NSPInspector.inspect(url: url)
                await MainActor.run {
                    report = index.report
                    inspectedURL = url
                    inspectedIndex = index
                    status = "PFS0 header and file ranges validated. This is not a game compatibility test."
                    busy = false
                }
            } catch {
                await MainActor.run {
                    status = "Inspection failed: " + error.localizedDescription
                    busy = false
                }
            }
        }
    }

    private func extractInspected() {
        guard let url = inspectedURL, let index = inspectedIndex else { return }
        busy = true
        status = "Extracting locally. This may use several GB of storage…"
        Task.detached(priority: .userInitiated) {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                let documents = FileManager.default.urls(for: .documentDirectory,
                    in: .userDomainMask)[0]
                let folder = documents.appendingPathComponent("nx18-extracted", isDirectory: true)
                    .appendingPathComponent(UUID().uuidString, isDirectory: true)
                let count = try NSPExtractor.extract(url: url, index: index,
                                                     destination: folder)
                await MainActor.run {
                    busy = false
                    status = "Extracted " + String(count) +
                        " encrypted files to Documents/nx18-extracted. No game was ported."
                }
            } catch {
                await MainActor.run {
                    busy = false
                    status = "Extraction failed: " + error.localizedDescription
                }
            }
        }
    }

    private func probeMetal() {
        busy = true
        metalStatus = "Compiling MSL on this iPhone…"
        Task.detached(priority: .userInitiated) {
            do {
                let result = try MetalProbe.run()
                await MainActor.run {
                    metalStatus = result
                    busy = false
                }
            } catch {
                await MainActor.run {
                    metalStatus = "FAIL: " + error.localizedDescription
                    busy = false
                }
            }
        }
    }


    private func loadKeys(_ url: URL) {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            let data = try Data(contentsOf: url)
            guard let text = String(data: data, encoding: .utf8) else {
                throw NCAHeader.Failure.invalidHex
            }
            switchKeys = try SwitchKeys(text: text)
            keyStatus = "Local prod.keys loaded in memory; nothing uploaded."
        } catch {
            switchKeys = nil
            keyStatus = "Key import failed: " + error.localizedDescription
        }
    }

    private func exportExeFS() {
        guard let url = inspectedURL, let index = inspectedIndex,
              let keys = switchKeys else { return }
        busy = true
        status = "Decrypting base-game ExeFS directly from selected NSP…"
        Task.detached(priority: .userInitiated) {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                let folder = FileManager.default.urls(for: .documentDirectory,
                    in: .userDomainMask)[0]
                    .appendingPathComponent("nx18-native-input", isDirectory: true)
                    .appendingPathComponent(UUID().uuidString, isDirectory: true)
                let output = try NCAPayload.exportExeFS(nsp: url, index: index,
                                                         keys: keys, destination: folder)
                await MainActor.run {
                    report = index.report + "\n\nDecrypted ExeFS\nTitle: " +
                        output.titleID + "\nNCA: " + output.ncaFile +
                        "\nModules: " + output.modules.joined(separator: ", ") +
                        "\nSaved in Files > On My iPhone > nx18 > nx18-native-input"
                    status = "ExeFS and SHA-256 manifest exported. Next: run scripts/continue-native18.ps1 on Windows to rewrite game code."
                    busy = false
                }
            } catch {
                await MainActor.run {
                    status = "ExeFS extraction failed: " + error.localizedDescription
                    busy = false
                }
            }
        }
    }

    private func inspectNCAHeaders() {
        guard let url = inspectedURL, let index = inspectedIndex,
              let key = switchKeys?.headerKey else { return }
        busy = true
        status = "Decrypting NCA headers locally…"
        Task.detached(priority: .userInitiated) {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                let rows = try NCAHeader.scan(nsp: url, index: index, headerKey: key)
                let expected = "0100B51020B68000"
                let hits = rows.filter { $0.titleHex == expected }
                var details = [
                    "Decrypted NCA headers: " + String(rows.count),
                    "Terminator 2D title-ID matches: " + String(hits.count)
                ]
                for row in rows.prefix(30) {
                    details.append(row.titleHex + "  " + row.contentLabel + "  " + row.name)
                }
                await MainActor.run {
                    report = index.report + "\n\n" + details.joined(separator: "\n")
                    status = rows.isEmpty
                        ? "No valid NCA headers found. Verify the header key and NSP."
                        : "NCA header scan finished. Match count is not proof of gameplay compatibility."
                    busy = false
                }
            } catch {
                await MainActor.run {
                    status = "NCA header check failed: " + error.localizedDescription
                    busy = false
                }
            }
        }
    }

}
