import Foundation
import CommonCrypto

/// A local keyset. Only prederived keys from the owner's own prod.keys are used;
/// key values are never written to disk or copied into an inspection report.
struct SwitchKeys {
    let headerKey: [UInt8]
    private let items: [String: [UInt8]]

    init(text: String) throws {
        var parsed: [String: [UInt8]] = [:]
        for raw in text.components(separatedBy: .newlines) {
            let split = raw.split(separator: "=", maxSplits: 1)
            guard split.count == 2 else { continue }
            let name = split[0].trimmingCharacters(in: .whitespaces).lowercased()
            let value = String(split[1].split(separator: "#", maxSplits: 1,
                                omittingEmptySubsequences: false).first ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty, value.count == 32 || value.count == 64 else { continue }
            var bytes: [UInt8] = []
            let chars = Array(value.utf8)
            for p in stride(from: 0, to: chars.count, by: 2) {
                guard let pair = String(bytes: chars[p..<(p + 2)], encoding: .ascii),
                      let byte = UInt8(pair, radix: 16) else {
                    throw NCAPayloadError.invalid("Invalid hex data in local key file")
                }
                bytes.append(byte)
            }
            parsed[name] = bytes
        }
        guard let header = parsed["header_key"] ?? parsed["nca_header_key"],
              header.count == 32 else {
            throw NCAPayloadError.invalid("prod.keys has no 32-byte header_key")
        }
        headerKey = header
        items = parsed
    }

    func require(_ name: String) throws -> [UInt8] {
        guard let value = items[name], value.count == 16 else {
            throw NCAPayloadError.invalid("Missing \(name) in local prod.keys")
        }
        return value
    }
}

enum NCAPayloadError: LocalizedError {
    case invalid(String), unsupported(String), shortRead
    var errorDescription: String? {
        switch self {
        case .invalid(let message): return message
        case .unsupported(let message): return message
        case .shortRead: return "NSP/NCA ended unexpectedly while reading game data"
        }
    }
}

/// Decrypts the NCA3 Program filesystem directly from the NSP, without
/// copying encrypted NCAs or requiring a separate desktop extraction.
/// Supported: unpatched AES-CTR ExeFS (key-area or common ticket).
/// Deliberately rejects BKTR updates, personalized tickets, and XTS sections.
enum NCAPayload {
    private static func le32(_ b: [UInt8], _ i: Int) -> UInt32 {
        UInt32(b[i]) | UInt32(b[i+1]) << 8 | UInt32(b[i+2]) << 16 | UInt32(b[i+3]) << 24
    }
    private static func le64(_ b: [UInt8], _ i: Int) -> UInt64 {
        UInt64(le32(b,i)) | UInt64(le32(b,i+4)) << 32
    }
    private static func hex(_ b: [UInt8]) -> String {
        b.map { String(format: "%02x", $0) }.joined()
    }
    private static func exact(_ h: FileHandle, offset: UInt64, count: Int) throws -> [UInt8] {
        try h.seek(toOffset: offset)
        guard let data = try h.read(upToCount: count), data.count == count else {
            throw NCAPayloadError.shortRead
        }
        return Array(data)
    }
    private static func sha(_ b: [UInt8]) -> [UInt8] {
        var out = [UInt8](repeating: 0, count: Int(CC_SHA256_DIGEST_LENGTH))
        b.withUnsafeBytes { raw in
            _ = CC_SHA256(raw.baseAddress, CC_LONG(b.count), &out)
        }
        return out
    }
    private static func ecb(_ b: [UInt8], key: [UInt8], encrypt: Bool) throws -> [UInt8] {
        guard key.count == 16, b.count % 16 == 0 else {
            throw NCAPayloadError.invalid("Invalid AES-128 block input")
        }
        var output = [UInt8](repeating: 0, count: b.count)
        var n = 0
        let status = key.withUnsafeBytes { k in
            b.withUnsafeBytes { input in
                output.withUnsafeMutableBytes { dst in
                    CCCrypt(encrypt ? CCOperation(kCCEncrypt) : CCOperation(kCCDecrypt),
                            CCAlgorithm(kCCAlgorithmAES), CCOptions(kCCOptionECBMode),
                            k.baseAddress, kCCKeySizeAES128, nil,
                            input.baseAddress, b.count, dst.baseAddress, b.count, &n)
                }
            }
        }
        guard status == kCCSuccess, n == b.count else {
            throw NCAPayloadError.invalid("AES processing failed")
        }
        return output
    }
    private static func addBE(_ bytes: inout [UInt8], _ index: Int, _ x: UInt64) {
        for j in 0..<8 {
            bytes[index + j] = UInt8(truncatingIfNeeded: x >> (8 * (7-j)))
        }
    }
    /// CTR offset is relative to the beginning of the NCA, NOT the NSP.
    /// Encrypt a batch of counters at once to avoid a cipher setup per block.
    static func cryptCTR(_ input: [UInt8], key: [UInt8],
                         sectionCounter: [UInt8], ncaOffset: UInt64) throws -> [UInt8] {
        guard sectionCounter.count == 8, key.count == 16 else {
            throw NCAPayloadError.invalid("Invalid section counter or key")
        }
        let skip = Int(ncaOffset % 16)
        let blocks = (input.count + skip + 15) / 16
        if blocks == 0 { return [] }
        guard blocks <= 65537 else { throw NCAPayloadError.invalid("AES-CTR chunk too large") }
        var counters = [UInt8](repeating: 0, count: blocks * 16)
        for i in 0..<blocks {
            let base = i * 16
            for j in 0..<8 { counters[base + j] = sectionCounter[7-j] }
            addBE(&counters, base + 8, (ncaOffset / 16) + UInt64(i))
        }
        let stream = try ecb(counters, key: key, encrypt: true)
        return input.enumerated().map { (i, v) in v ^ stream[i + skip] }
    }

    struct Export {
        let titleID: String
        let ncaFile: String
        let modules: [String]
        let destination: URL
    }

    private struct NCASection {
        let start: UInt64  // absolute offset relative to the NCA
        let bytes: UInt64
        let header: [UInt8]
        let key: [UInt8]?
        let pfsOffset: UInt64
        let pfsSize: UInt64
    }

    private static func readSection(_ h: FileHandle, ncaBase: UInt64,
                                    sec: NCASection, offset: UInt64,
                                    count: Int) throws -> [UInt8] {
        guard offset <= sec.bytes, UInt64(count) <= sec.bytes - offset else {
            throw NCAPayloadError.invalid("NCA ExeFS section is out of bounds")
        }
        let raw = try exact(h, offset: ncaBase + sec.start + offset, count: count)
        guard let key = sec.key else { return raw }
        return try cryptCTR(raw, key: key,
                            sectionCounter: Array(sec.header[0x140..<0x148]),
                            ncaOffset: sec.start + offset)
    }

    private static func sectionKey(_ h: FileHandle, index: NSPIndex,
                                   ncaHeader: [UInt8], keys: SwitchKeys) throws -> [UInt8] {
        let generation = max(ncaHeader[0x206], ncaHeader[0x220])
        let keyIndex = generation > 0 ? Int(generation) - 1 : 0
        let suffix = String(format: "%02x", keyIndex)
        let rights = Array(ncaHeader[0x230..<0x240])
        if rights.contains(where: { $0 != 0 }) {
            // Ticket common title key at 0x180, rights id at 0x2A0.
            // Personalized tickets contain an RSA-encrypted title key and
            // are deliberately NOT accepted by this AES path.
            for entry in index.entries where entry.name.lowercased().hasSuffix(".tik") {
                if entry.length < 0x2B0 { continue }
                let ticket = try exact(h, offset: entry.offset, count: 0x2B0)
                if Array(ticket[0x2A0..<0x2B0]) != rights { continue }
                guard ticket[0x285] == 0 else {
                    throw NCAPayloadError.unsupported("Personalized tickets cannot be decrypted by this importer")
                }
                return try ecb(Array(ticket[0x180..<0x190]),
                               key: keys.require("titlekek_" + suffix), encrypt: false)
            }
            throw NCAPayloadError.invalid("The NSP has no matching common ticket for its Rights ID")
        }
        let groups = ["application", "ocean", "system"]
        let group = Int(ncaHeader[0x207])
        guard group < groups.count else {
            throw NCAPayloadError.unsupported("Unsupported NCA key-area index")
        }
        let areaKey = try keys.require("key_area_key_" + groups[group] + "_" + suffix)
        // Standard AES-CTR sections use decrypted key-area slot 2.
        return try ecb(Array(ncaHeader[0x320..<0x330]), key: areaKey, encrypt: false)
    }

    private static func parseSection(_ h: FileHandle, ncaBase: UInt64,
                                     ncaBytes: UInt64, header: [UInt8],
                                     keys: SwitchKeys, index: NSPIndex) throws -> NCASection? {
        for s in 0..<4 {
            let info = 0x240 + s * 0x10
            let startMedia = UInt64(le32(header, info))
            let endMedia = UInt64(le32(header, info+4))
            if startMedia == 0 && endMedia == 0 { continue }
            guard startMedia >= 6, endMedia > startMedia,
                  endMedia <= ncaBytes / 0x200 else {
                throw NCAPayloadError.invalid("NCA filesystem section exceeds NCA bounds")
            }
            let fs = Array(header[(0x400+s*0x200)..<(0x600+s*0x200)])
            guard sha(fs) == Array(header[(0x280+s*0x20)..<(0x2A0+s*0x20)]) else {
                throw NCAPayloadError.invalid("NCA filesystem header SHA-256 mismatch")
            }
            guard fs[2] == 1 && fs[3] == 2 else { continue }  // PartitionFS / PFS0
            let crypt = fs[4]
            guard crypt == 1 || crypt == 3 else {
                throw NCAPayloadError.unsupported("Program ExeFS uses unsupported section crypt type \(crypt)")
            }
            let start = startMedia * 0x200
            let length = (endMedia - startMedia) * 0x200
            let pfsOffset = le64(fs, 0x40)
            let pfsSize = le64(fs, 0x48)
            guard pfsSize >= 0x10, pfsOffset <= length, pfsSize <= length - pfsOffset else {
                throw NCAPayloadError.invalid("Invalid ExeFS PFS0 superblock range")
            }
            let key = crypt == 3 ? try sectionKey(h, index: index, ncaHeader: header, keys: keys) : nil
            let section = NCASection(start: start, bytes: length, header: fs,
                                     key: key, pfsOffset: pfsOffset, pfsSize: pfsSize)
            let hashTableOffset = le64(fs, 0x30)
            let hashTableSize = le64(fs, 0x38)
            guard hashTableSize > 0, hashTableSize <= 8*1024*1024,
                  hashTableOffset <= length, hashTableSize <= length - hashTableOffset else {
                throw NCAPayloadError.invalid("Invalid ExeFS hash-table bounds")
            }
            let hashTable = try readSection(h, ncaBase: ncaBase, sec: section,
                                            offset: hashTableOffset,
                                            count: Int(hashTableSize))
            guard sha(hashTable) == Array(fs[8..<0x28]) else {
                throw NCAPayloadError.invalid("ExeFS hash table mismatch (wrong key or corrupted NSP)")
            }
            return section
        }
        return nil
    }

    /// Extracts the actual decrypted ExeFS files (main/rtld/sdk/subsdk*/main.npdm)
    /// from the first Program NCA that has a valid PFS0 section.
    /// Does not run the modules, recompile them or decrypt RomFS.
    static func exportExeFS(nsp: URL, index: NSPIndex, keys: SwitchKeys,
                            destination: URL) throws -> Export {
        let fm = FileManager.default
        guard !fm.fileExists(atPath: destination.path) else {
            throw NCAPayloadError.invalid("Export destination already exists")
        }
        let h = try FileHandle(forReadingFrom: nsp)
        defer { try? h.close() }
        var foundProgram = false
        for nca in index.entries where nca.name.lowercased().hasSuffix(".nca") && nca.length >= 0xC00 {
            let encrypted = try exact(h, offset: nca.offset, count: 0xC00)
            let header = try NCAHeader.cryptSectors(encrypted, headerKey: keys.headerKey,
                                                     startingSector: 0, encrypt: false)
            guard Array(header[0x200..<0x204]) == Array("NCA3".utf8),
                  header[0x205] == 0 else { continue }
            foundProgram = true
            let title = String(format: "%016llX", le64(header, 0x210))
            let declared = le64(header, 0x208)
            guard declared >= 0xC00, declared <= nca.length else {
                throw NCAPayloadError.invalid("NCA declared size extends outside NSP")
            }
            guard let section = try parseSection(h, ncaBase: nca.offset,
                                                 ncaBytes: declared, header: header,
                                                 keys: keys, index: index) else { continue }
            let first = try readSection(h, ncaBase: nca.offset, sec: section,
                                        offset: section.pfsOffset, count: 0x10)
            guard Array(first.prefix(4)) == Array("PFS0".utf8) else {
                throw NCAPayloadError.invalid("Decrypted ExeFS does not contain PFS0")
            }
            let count = Int(le32(first, 4)), namesSize = Int(le32(first, 8))
            guard count > 0, count <= 128, namesSize > 0, namesSize <= 65536 else {
                throw NCAPayloadError.invalid("ExeFS file table is unreasonable")
            }
            let metaBytes = count*24 + namesSize
            guard UInt64(16 + metaBytes) <= section.pfsSize else {
                throw NCAPayloadError.invalid("ExeFS filename table outside PFS0")
            }
            let metadata = try readSection(h, ncaBase: nca.offset, sec: section,
                                           offset: section.pfsOffset + 16, count: metaBytes)
            let dataStart = UInt64(16+metaBytes)
            var files: [(String, UInt64, UInt64)] = []
            var seen = Set<String>()
            for i in 0..<count {
                let at = i*24
                let relative = le64(metadata, at)
                let size = le64(metadata, at+8)
                let nameAt = Int(le32(metadata, at+16)) + count*24
                guard nameAt < metadata.count,
                      let end = metadata[nameAt...].firstIndex(of: 0),
                      end > nameAt,
                      let name = String(bytes: metadata[nameAt..<end], encoding: .utf8),
                      !name.contains("/"), !name.contains("\\"),
                      name != "." && name != "..", seen.insert(name).inserted,
                      dataStart <= section.pfsSize,
                      relative <= section.pfsSize - dataStart,
                      size <= section.pfsSize - dataStart - relative else {
                    throw NCAPayloadError.invalid("Malformed or unsafe ExeFS entry \(i)")
                }
                files.append((name, dataStart+relative, size))
            }
            guard files.contains(where: { $0.0 == "main" }) else { continue }
            try fm.createDirectory(at: destination, withIntermediateDirectories: true)
            var completed = false
            defer { if !completed { try? fm.removeItem(at: destination) } }
            for (name, rel, size) in files {
                let target = destination.appendingPathComponent(name)
                guard fm.createFile(atPath: target.path, contents: nil) else {
                    throw NCAPayloadError.invalid("Cannot create ExeFS output file")
                }
                let out = try FileHandle(forWritingTo: target)
                defer { try? out.close() }
                var offset: UInt64 = 0
                while offset < size {
                    let amount = Int(min(1024*1024, size-offset))
                    let chunk = try readSection(h, ncaBase: nca.offset, sec: section,
                                                offset: section.pfsOffset+rel+offset,
                                                count: amount)
                    try out.write(contentsOf: Data(chunk))
                    offset += UInt64(amount)
                }
                try out.close()
            }
            let main = try FileHandle(forReadingFrom: destination.appendingPathComponent("main"))
            defer { try? main.close() }
            let signature = try exact(main, offset: 0, count: 4)
            guard signature == Array("NSO0".utf8) else {
                throw NCAPayloadError.invalid("Decrypted ExeFS main is not an NSO0 executable")
            }
            completed = true
            return Export(titleID: title, ncaFile: nca.name,
                          modules: files.map { $0.0 }, destination: destination)
        }
        throw NCAPayloadError.unsupported(foundProgram
            ? "Program NCA contains no supported base-game ExeFS"
            : "NSP contains no readable NCA3 Program archive")
    }
}
