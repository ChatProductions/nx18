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
    @State private var showingImporter = false
    @State private var busy = false
    @State private var status = "No NSP imported."
    @State private var report = ""
    @State private var inspectedURL: URL?
    @State private var inspectedIndex: NSPIndex?
    @State private var metalStatus = "Not tested on this device."
    @State private var showingKeyImporter = false
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
                        showingImporter = true
                    } label: {
                        Label("Inspect NSP on this iPhone", systemImage: "doc.text.magnifyingglass")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy)

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
                            showingKeyImporter = true
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
            .fileImporter(isPresented: $showingImporter, allowedContentTypes: [.item]) { result in
                switch result {
                case .success(let url): inspect(url)
                case .failure(let error): status = "File picker: " + error.localizedDescription
                }
            }
            .fileImporter(isPresented: $showingKeyImporter, allowedContentTypes: [.item]) { result in
                switch result {
                case .success(let url): loadKeys(url)
                case .failure(let error): keyStatus = "Key picker: " + error.localizedDescription
                }
            }
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
                    status = "ExeFS extracted. Native ARM64 rewriting and IPA signing still required."
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
