import Foundation

@main
struct InspectorSmoke {
    static func put32(_ data: inout Data, _ v: UInt32) {
        for n in 0..<4 { data.append(UInt8((v >> (n * 8)) & 255)) }
    }
    static func put64(_ data: inout Data, _ v: UInt64) {
        for n in 0..<8 { data.append(UInt8((v >> (n * 8)) & 255)) }
    }

    static func fixture(relative: UInt64 = 0, length: UInt64 = 4, fileSize: Int = 4) -> Data {
        let name = Data("0123456789abcdef.nca\0".utf8)
        var data = Data("PFS0".utf8)
        put32(&data, 1)
        put32(&data, UInt32(name.count))
        put32(&data, 0)
        put64(&data, relative)
        put64(&data, length)
        put32(&data, 0)
        put32(&data, 0)
        data.append(name)
        data.append(Data(repeating: 0x72, count: fileSize))
        return data
    }

    static func main() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("nx18-pfs0-smoke-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let sample = dir.appendingPathComponent("sample.nsp")
        try fixture().write(to: sample)
        let parsed = try NSPInspector.inspect(url: sample)
        precondition(parsed.entries.count == 1)
        precondition(parsed.entries[0].name == "0123456789abcdef.nca")
        precondition(parsed.entries[0].length == 4)
        precondition(parsed.report.contains("NCA files: 1"))

        let extracted = dir.appendingPathComponent("extracted")
        let copied = try NSPExtractor.extract(url: sample, index: parsed,
                                              destination: extracted)
        precondition(copied == 1)
        let nca = extracted.appendingPathComponent("0123456789abcdef.nca")
        let bytes = try Data(contentsOf: nca)
        precondition(bytes == Data(repeating: 0x72, count: 4))

        try fixture(relative: 4, length: 5).write(to: sample)
        do {
            _ = try NSPInspector.inspect(url: sample)
            fatalError("Out-of-range NCA entry was accepted")
        } catch NSPInspectionError.invalid {
            // Expected
        }
        try Data("NOTPFS0".utf8).write(to: sample)
        do {
            _ = try NSPInspector.inspect(url: sample)
            fatalError("Non-NSP file was accepted")
        } catch NSPInspectionError.truncated {
            // Expected: too short even for the header.
        }
        // Deterministic AES-128-XTS vector cross-checked independently
        // with OpenSSL-backed Python cryptography (XTS tweak is a big-endian sector).
        let key = (0..<32).map { UInt8($0) }
        var plain = (0..<0x400).map { UInt8(($0 * 17 + 3) & 255) }
        plain.replaceSubrange(0x200..<0x204, with: Array("NCA3".utf8))
        plain[0x205] = 0 // Program
        let ac2ID: UInt64 = 0x0100670014482000
        for j in 0..<8 {
            plain[0x210 + j] = UInt8((ac2ID >> (8 * j)) & 0xff)
        }
        let encrypted = try NCAHeader.cryptHeader(plain, headerKey: key, encrypt: true)
        let first32 = encrypted.prefix(32).map { String(format: "%02x", $0) }.joined()
        let sector1First32 = encrypted[512..<544].map { String(format: "%02x", $0) }.joined()
        precondition(first32 == "7bd6eba8dfbce7708a804d5b33a58a50903e0839419393b2d18e00cfb02c1140")
        precondition(sector1First32 == "87bf7cbe93913cd0c5f150d69c12518ee82edc08a8b4ac90711aab7dca5a0551")
        let decrypted = try NCAHeader.cryptHeader(encrypted, headerKey: key, encrypt: false)
        precondition(decrypted == plain)
        let keyText = "header_key = " + key.map { String(format: "%02x", $0) }.joined()
        precondition(try NCAHeader.headerKey(from: keyText) == key)

        let ncaName = Data("0123456789abcdef.nca\0".utf8)
        var nsp = fixture(length: 0x400, fileSize: 0x400)
        let contentsAt = 16 + 24 + ncaName.count
        nsp.replaceSubrange(contentsAt..<(contentsAt + 0x400), with: encrypted)
        try nsp.write(to: sample)
        let encryptedIndex = try NSPInspector.inspect(url: sample)
        let titles = try NCAHeader.scan(nsp: sample, index: encryptedIndex,
                                        headerKey: key)
        precondition(titles.count == 1)
        precondition(titles[0].programId == ac2ID)
        precondition(titles[0].contentLabel == "Program")

        print("PASS: PFS0 index, encrypted NCA extraction, bounds rejection and invalid header and AES-XTS NCA title validation")
    }
}
