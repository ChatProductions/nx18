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
        print("PASS: PFS0 index, encrypted NCA extraction, bounds rejection and invalid header")
    }
}
