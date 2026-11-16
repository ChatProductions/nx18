import Foundation

/// Copies the files inside a validated PFS0 container to an app-owned directory.
/// NCA files stay encrypted. This is extraction, NOT decryption or executable porting.
enum NSPExtractor {
    enum Failure: LocalizedError {
        case cannotCreateOutput, sourceChanged
        var errorDescription: String? {
            switch self {
            case .cannotCreateOutput: return "Could not create a local extraction file."
            case .sourceChanged: return "Source NSP changed or ended during extraction."
            }
        }
    }

    /// destination must be a fresh app-owned directory; caller creates a unique path.
    @discardableResult
    static func extract(url: URL, index: NSPIndex, destination: URL) throws -> Int {
        let fm = FileManager.default
        guard !fm.fileExists(atPath: destination.path) else {
            throw NSPInspectionError.invalid("extraction destination already exists")
        }
        try fm.createDirectory(at: destination, withIntermediateDirectories: true)
        var completed = false
        defer {
            if !completed { try? fm.removeItem(at: destination) }
        }

        let source = try FileHandle(forReadingFrom: url)
        defer { try? source.close() }
        var seen = Set<String>()
        for entry in index.entries {
            // Revalidate exact file names, even if a future importer builds an index differently.
            guard !entry.name.isEmpty && entry.name != "." && entry.name != ".." &&
                  !entry.name.contains("/") && !entry.name.contains("\\") &&
                  seen.insert(entry.name).inserted else {
                throw NSPInspectionError.invalid("duplicate or unsafe file name")
            }
            let target = destination.appendingPathComponent(entry.name, isDirectory: false)
            guard fm.createFile(atPath: target.path, contents: nil) else {
                throw Failure.cannotCreateOutput
            }
            let output = try FileHandle(forWritingTo: target)
            do {
                try source.seek(toOffset: entry.offset)
                var remaining = entry.length
                while remaining > 0 {
                    let amount = Int(min(remaining, 1024 * 1024))
                    guard let block = try source.read(upToCount: amount), !block.isEmpty else {
                        throw Failure.sourceChanged
                    }
                    try output.write(contentsOf: block)
                    remaining -= UInt64(block.count)
                }
                try output.close()
            } catch {
                try? output.close()
                throw error
            }
        }
        completed = true
        return index.entries.count
    }
}
