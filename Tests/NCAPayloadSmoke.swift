import Foundation
import CommonCrypto

/// Synthetic encrypted NCA3 Program archive, all keys/data generated in test.
/// Exercises the REAL AES-XTS header, AES-CTR section, key-area and ticket paths.
@main
struct NCAPayloadSmoke {
    static func put32(_ b: inout [UInt8], _ i: Int, _ n: UInt32) {
        for j in 0..<4 { b[i+j] = UInt8(truncatingIfNeeded: n >> (j*8)) }
    }
    static func put64(_ b: inout [UInt8], _ i: Int, _ n: UInt64) {
        for j in 0..<8 { b[i+j] = UInt8(truncatingIfNeeded: n >> (j*8)) }
    }
    static func hex(_ b: [UInt8]) -> String {
        b.map { String(format: "%02x", $0) }.joined()
    }
    static func sha(_ b: [UInt8]) -> [UInt8] {
        var out = [UInt8](repeating: 0, count: Int(CC_SHA256_DIGEST_LENGTH))
        b.withUnsafeBytes { _ = CC_SHA256($0.baseAddress, CC_LONG(b.count), &out) }
        return out
    }
    static func ecb(_ b: [UInt8], _ key: [UInt8], encrypt: Bool) -> [UInt8] {
        var out = [UInt8](repeating: 0, count: b.count)
        var count = 0
        let size = b.count
        let rc = key.withUnsafeBytes { k in
            b.withUnsafeBytes { input in
                out.withUnsafeMutableBytes { output in
                    CCCrypt(encrypt ? CCOperation(kCCEncrypt) : CCOperation(kCCDecrypt),
                            CCAlgorithm(kCCAlgorithmAES), CCOptions(kCCOptionECBMode),
                            k.baseAddress, 16, nil, input.baseAddress, size,
                            output.baseAddress, size, &count)
                }
            }
        }
        precondition(rc == kCCSuccess && count == size)
        return out
    }
    static func makeNSP(ticketed: Bool, headerKey: [UInt8],
                        areaKey: [UInt8], titlekek: [UInt8],
                        dataKey: [UInt8]) throws -> Data {
        let ncaBytes = 0x4000, sectionStart = 0xC00, sectionSize = ncaBytes - sectionStart
        let title: UInt64 = 0x0100B51020B68000
        let rights: [UInt8] = Array(1...16)
        let main: [UInt8] = Array("NSO0".utf8) + [UInt8](repeating: 0, count: 60)
        let filename = Array("main\0".utf8)
        var pfs = [UInt8](repeating: 0, count: 0x10 + 0x18 + filename.count + main.count)
        pfs.replaceSubrange(0..<4, with: Array("PFS0".utf8))
        put32(&pfs, 4, 1)
        put32(&pfs, 8, UInt32(filename.count))
        put64(&pfs, 0x18, UInt64(main.count))
        pfs.replaceSubrange(0x28..<(0x28+filename.count), with: filename)
        let payload = 0x10 + 0x18 + filename.count
        pfs.replaceSubrange(payload..<(payload+main.count), with: main)

        var fs = [UInt8](repeating: 0, count: 0x200)
        fs[2] = 1; fs[3] = 2; fs[4] = 3
        put32(&fs, 0x28, 0x1000)
        put32(&fs, 0x2C, 2)
        put64(&fs, 0x30, 0)
        put64(&fs, 0x38, 0x20)
        put64(&fs, 0x40, 0x200)
        put64(&fs, 0x48, UInt64(pfs.count))
        fs.replaceSubrange(8..<0x28, with: sha(sha(pfs)))
        fs[0x140] = 0x44; fs[0x143] = 0x10
        let mutKey = ticketed ? dataKey : ecb(ecb(dataKey, areaKey, encrypt: true), areaKey, encrypt: false)
        precondition(mutKey == dataKey)

        var section = [UInt8](repeating: 0, count: sectionSize)
        section.replaceSubrange(0..<0x20, with: sha(pfs))
        section.replaceSubrange(0x200..<(0x200+pfs.count), with: pfs)
        section = try NCAPayload.cryptCTR(section, key: dataKey,
                                           sectionCounter: Array(fs[0x140..<0x148]),
                                           ncaOffset: UInt64(sectionStart))

        var header = [UInt8](repeating: 0, count: 0xC00)
        header.replaceSubrange(0x200..<0x204, with: Array("NCA3".utf8))
        header[0x205] = 0
        header[0x206] = 1
        header[0x207] = 0
        put64(&header, 0x208, UInt64(ncaBytes))
        put64(&header, 0x210, title)
        put32(&header, 0x240, UInt32(sectionStart/0x200))
        put32(&header, 0x244, UInt32(ncaBytes/0x200))
        header.replaceSubrange(0x280..<0x2A0, with: sha(fs))
        if ticketed {
            header.replaceSubrange(0x230..<0x240, with: rights)
        } else {
            header.replaceSubrange(0x320..<0x330, with: ecb(dataKey, areaKey, encrypt: true))
        }
        header.replaceSubrange(0x400..<0x600, with: fs)
        let cryptHeader = try NCAHeader.cryptSectors(header, headerKey: headerKey,
                                                     startingSector: 0, encrypt: true)
        let nca = cryptHeader + section

        var ticket = [UInt8](repeating: 0, count: 0x2C0)
        ticket[0x281] = 0 // Common title-key type; 0x285 is a master-key revision.
        ticket[0x285] = 1 // Nonzero revision must not be mistaken for personalized ticket
        ticket.replaceSubrange(0x180..<0x190, with: ecb(dataKey, titlekek, encrypt: true))
        ticket.replaceSubrange(0x2A0..<0x2B0, with: rights)
        let names = Array((ticketed ? "sample.nca\0sample.tik\0" : "sample.nca\0").utf8)
        let count = ticketed ? 2 : 1
        let headerSize = 16 + count*24 + names.count
        var nsp = [UInt8](repeating: 0, count: headerSize)
        nsp.replaceSubrange(0..<4, with: Array("PFS0".utf8))
        put32(&nsp, 4, UInt32(count))
        put32(&nsp, 8, UInt32(names.count))
        put64(&nsp, 0x10 + 8, UInt64(ncaBytes))
        if ticketed {
            put64(&nsp, 0x10+24, UInt64(ncaBytes))
            put64(&nsp, 0x10+24+8, UInt64(ticket.count))
            put32(&nsp, 0x10+24+16, UInt32("sample.nca\0".utf8.count))
        }
        nsp.replaceSubrange((16+count*24)..<headerSize, with: names)
        nsp += nca
        if ticketed { nsp += ticket }
        return Data(nsp)
    }

    static func main() throws {
        let header = (0..<32).map { UInt8($0) }
        let area = (20..<36).map { UInt8($0) }
        let titlekek = (40..<56).map { UInt8($0) }
        let dataKey = (60..<76).map { UInt8($0) }
        let keyText = "header_key = " + hex(header) + "\n"
                    + "key_area_key_application_00 = " + hex(area) + "\n"
                    + "titlekek_00 = " + hex(titlekek) + "\n"
        let keys = try SwitchKeys(text: keyText)
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("nx18-nca-smoke-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        for ticketed in [false, true] {
            let source = dir.appendingPathComponent(ticketed ? "rights.nsp" : "area.nsp")
            try makeNSP(ticketed: ticketed, headerKey: header,
                        areaKey: area, titlekek: titlekek, dataKey: dataKey).write(to: source)
            let idx = try NSPInspector.inspect(url: source)
            let dest = dir.appendingPathComponent(ticketed ? "rights" : "area")
            let export = try NCAPayload.exportExeFS(nsp: source, index: idx,
                                                     keys: keys, destination: dest)
            precondition(export.titleID == "0100B51020B68000")
            precondition(export.modules == ["main"])
            let main = try Data(contentsOf: dest.appendingPathComponent("main"))
            precondition(main.prefix(4) == Data("NSO0".utf8))
            precondition(main.count == 64)
            let manifest = dest.appendingPathComponent("nx18-export.json")
            let export = try JSONSerialization.jsonObject(
                with: Data(contentsOf: manifest)) as! [String: Any]
            precondition(export["title_id"] as? String == "0100B51020B68000")
            precondition(export["stage"] as? String == "decrypted-exefs")
            precondition(export["keys_embedded"] as? Bool == false)
            let records = export["files"] as! [[String: Any]]
            precondition(records.count == 1)
            precondition(records[0]["name"] as? String == "main")
            precondition(records[0]["size_bytes"] as? UInt64 == 64 ||
                         records[0]["size_bytes"] as? Int == 64)
        }
        let personalized = dir.appendingPathComponent("personalized.nsp")
        var personalizedData = try makeNSP(ticketed: true, headerKey: header,
                                           areaKey: area, titlekek: titlekek,
                                           dataKey: dataKey)
        let candidate = dir.appendingPathComponent("ticket-offset.nsp")
        try personalizedData.write(to: candidate)
        let containerIndex = try NSPInspector.inspect(url: candidate)
        guard let ticketEntry = containerIndex.entries.first(where: { $0.name.hasSuffix(".tik") }) else {
            fatalError("Synthetic ticket missing")
        }
        let offset = Int(ticketEntry.offset)
        personalizedData[offset + 0x281] = 1
        try personalizedData.write(to: personalized)
        do {
            let parsed = try NSPInspector.inspect(url: personalized)
            _ = try NCAPayload.exportExeFS(nsp: personalized, index: parsed,
                                           keys: keys, destination: dir.appendingPathComponent("personalized"))
            fatalError("Personalized ticket was incorrectly treated as common ticket")
        } catch NCAPayloadError.unsupported {
            // Expected.
        }

        let bad = dir.appendingPathComponent("wrong.nsp")
        try makeNSP(ticketed: false, headerKey: header,
                    areaKey: area, titlekek: titlekek, dataKey: dataKey).write(to: bad)
        let index = try NSPInspector.inspect(url: bad)
        let wrongKeys = try SwitchKeys(text: keyText.replacingOccurrences(
            of: hex(area), with: hex([UInt8](repeating: 0xEE, count: 16))))
        do {
            _ = try NCAPayload.exportExeFS(nsp: bad, index: index, keys: wrongKeys,
                                           destination: dir.appendingPathComponent("wrong"))
            fatalError("Decrypted bogus ExeFS using the wrong key")
        } catch NCAPayloadError.invalid {
            // Expected: hash-table verification rejects the wrong key.
        }
        print("PASS: encrypted NCA3 Program ExeFS using key area and common ticket; wrong key rejected")
    }
}
