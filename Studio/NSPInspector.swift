import Foundation

struct NSPIndex {
    struct Entry {
        let name: String
        let offset: UInt64
        let length: UInt64
    }

    let fileName: String
    let containerBytes: UInt64
    let entries: [Entry]

    var report: String {
        var lines = [
            "nx18 / NSP container inspection",
            "File: " + fileName,
            "Bytes: " + String(containerBytes),
            "PFS0 entries: " + String(entries.count),
            "NCA files: " + String(entries.filter { $0.name.lowercased().hasSuffix(".nca") }.count),
            "Tickets: " + String(entries.filter { $0.name.lowercased().hasSuffix(".tik") }.count),
            "NOTE: No NCA decryption or title verification.",
            ""
        ]
        for entry in entries.prefix(128) {
            lines.append(entry.name + " [" + String(entry.offset) + ", " + String(entry.length) + " bytes]")
        }
        if entries.count > 128 {
            lines.append("… and " + String(entries.count - 128) + " more entries")
        }
        return lines.joined(separator: "\n")
    }
}

enum NSPInspectionError: LocalizedError {
    case unsupported, truncated, invalid(String)
    var errorDescription: String? {
        switch self {
        case .unsupported:
            return "Only PFS0 .nsp files are supported. XCI/HFS0 and compressed NSZ need separate parsers."
        case .truncated: return "The file ends before the declared container data."
        case .invalid(let reason): return "Invalid NSP: " + reason
        }
    }
}

enum NSPInspector {
    private static func u32(_ b: [UInt8], _ at: Int) -> UInt32 {
        UInt32(b[at]) | (UInt32(b[at + 1]) << 8) |
        (UInt32(b[at + 2]) << 16) | (UInt32(b[at + 3]) << 24)
    }

    private static func u64(_ b: [UInt8], _ at: Int) -> UInt64 {
        UInt64(u32(b, at)) | (UInt64(u32(b, at + 4)) << 32)
    }

    private static func exactly(_ handle: FileHandle, _ n: Int) throws -> [UInt8] {
        guard let data = try handle.read(upToCount: n), data.count == n else {
            throw NSPInspectionError.truncated
        }
        return [UInt8](data)
    }

    static func inspect(url: URL) throws -> NSPIndex {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let total = try handle.seekToEnd()
        guard total >= 16 else { throw NSPInspectionError.truncated }
        try handle.seek(toOffset: 0)
        let header = try exactly(handle, 16)
        guard Array(header[0..<4]) == Array("PFS0".utf8) else {
            throw NSPInspectionError.unsupported
        }
        let count = Int(u32(header, 4))
        let namesLength = Int(u32(header, 8))
        guard count > 0 && count <= 65_536 else {
            throw NSPInspectionError.invalid("file-count limit")
        }
        guard namesLength > 0 && namesLength <= 16 * 1024 * 1024 else {
            throw NSPInspectionError.invalid("string-table length")
        }
        let recordBytes = UInt64(count) * 24
        let nameBytes = UInt64(namesLength)
        guard recordBytes <= total - 16 &&
              nameBytes <= total - 16 - recordBytes else {
            throw NSPInspectionError.truncated
        }
        let payloadStart = 16 + recordBytes + nameBytes
        let records = try exactly(handle, count * 24)
        let names = try exactly(handle, namesLength)
        var entries: [NSPIndex.Entry] = []
        entries.reserveCapacity(count)

        for i in 0..<count {
            let at = i * 24
            let relative = u64(records, at)
            let length = u64(records, at + 8)
            let stringOffset = Int(u32(records, at + 16))
            guard stringOffset < names.count else {
                throw NSPInspectionError.invalid("filename offset for entry " + String(i))
            }
            guard let end = names[stringOffset...].firstIndex(of: 0) else {
                throw NSPInspectionError.invalid("unterminated filename")
            }
            guard end > stringOffset,
                  let filename = String(bytes: names[stringOffset..<end], encoding: .utf8),
                  !filename.contains("/"), !filename.contains("\\"),
                  filename != "." && filename != ".." else {
                throw NSPInspectionError.invalid("unsafe or invalid filename")
            }
            let payloadBytes = total - payloadStart
            guard relative <= payloadBytes && length <= payloadBytes - relative else {
                throw NSPInspectionError.invalid("entry " + String(i) + " extends past the file")
            }
            entries.append(NSPIndex.Entry(name: filename,
                                          offset: payloadStart + relative,
                                          length: length))
        }
        return NSPIndex(fileName: url.lastPathComponent,
                        containerBytes: total,
                        entries: entries)
    }
}
