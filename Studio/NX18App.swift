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

                    GroupBox("Assassin's Creed II — Switch") {
                        VStack(alignment: .leading, spacing: 9) {
                            Text("The Ezio Collection")
                                .font(.headline)
                            Text("Title ID: 0100670014482000")
                                .font(.caption.monospaced())
                            Text("Import a base-game NSP to inspect its PFS0 contents. NCA files remain encrypted; title and update verification is not implemented.")
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
                        ProgressView("Reading container headers…")
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

                    GroupBox("Porting status") {
                        VStack(alignment: .leading, spacing: 6) {
                            Label("PFS0/NSP indexing: implemented", systemImage: "checkmark.circle")
                            Label("NCA decryption and updates: not implemented", systemImage: "circle.dashed")
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
        }
    }

    private func inspect(_ url: URL) {
        busy = true
        report = ""
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
}
