import Foundation
import CommonCrypto

/// Reads only the encrypted NCA header inside a PFS0 NSP.
/// Does NOT decrypt the NCA's filesystem/data and does not handle tickets.
struct NCAHeaderInfo {
    let name: String
    let programId: UInt64
    let contentType: UInt8
    var titleHex: String { String(format: "%016llX", programId) }
    var contentLabel: String {
        switch contentType {
        case 0: return "Program"
        case 1: return "Meta"
        case 2: return "Control"
        case 3: return "Manual"
        case 4: return "Data"
        case 5: return "PublicData"
        default: return "Unknown"
        }
    }
}

enum NCAHeader {
    enum Failure: LocalizedError {
        case missingKey, invalidHex, cipher
        var errorDescription: String? {
            switch self {
            case .missingKey: return "No 32-byte NCA header key in the provided key file."
            case .invalidHex: return "Malformed NCA header key: expected 64 hex digits."
            case .cipher: return "AES-XTS header processing failed."
            }
        }
    }

    /// Accepts common prod.keys spellings. No key material is saved or logged.
    static func headerKey(from text: String) throws -> [UInt8] {
        for line in text.components(separatedBy: .newlines) {
            let parts = line.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else { continue }
            let name = parts[0].trimmingCharacters(in: .whitespaces).lowercased()
            guard name == "header_key" || name == "nca_header_key" else { continue }
            let hex = parts[1].split(separator: "#", maxSplits: 1)[0]
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard hex.count == 64 else { throw Failure.invalidHex }
            let chars = Array(hex.utf8)
            var result = [UInt8]()
            result.reserveCapacity(32)
            for i in stride(from: 0, to: 64, by: 2) {
                guard let pair = String(bytes: chars[i..<(i + 2)], encoding: .ascii),
                      let byte = UInt8(pair, radix: 16) else { throw Failure.invalidHex }
                result.append(byte)
            }
            return result
        }
        throw Failure.missingKey
    }

    private static func aesBlock(_ block: [UInt8], key: [UInt8],
                                 encrypt: Bool) throws -> [UInt8] {
        guard block.count == 16 && key.count == 16 else { throw Failure.cipher }
        var output = [UInt8](repeating: 0, count: 16)
        var processed = 0
        let status = key.withUnsafeBytes { keyBytes in
            block.withUnsafeBytes { inputBytes in
                output.withUnsafeMutableBytes { outputBytes in
                    CCCrypt(encrypt ? CCOperation(kCCEncrypt) : CCOperation(kCCDecrypt),
                            CCAlgorithm(kCCAlgorithmAES),
                            CCOptions(kCCOptionECBMode),
                            keyBytes.baseAddress, kCCKeySizeAES128, nil,
                            inputBytes.baseAddress, 16,
                            outputBytes.baseAddress, 16, &processed)
                }
            }
        }
        guard status == kCCSuccess && processed == 16 else { throw Failure.cipher }
        return output
    }

    private static func multiplyAlpha(_ tweak: inout [UInt8]) {
        var carry: UInt8 = 0
        for i in 0..<16 {
            let next = tweak[i] >> 7
            tweak[i] = (tweak[i] &<< 1) | carry
            carry = next
        }
        if carry != 0 { tweak[0] ^= 0x87 }
    }

    /// Nintendo NCA AES-128-XTS: 0x200-byte sectors; sector index
    /// is encoded as a 16-byte BIG-endian integer before tweak encryption.
    /// The first 0x400 bytes suffice to check NCA3 magic and ProgramId.
    static func cryptHeader(_ input: [UInt8], headerKey: [UInt8],
                            encrypt: Bool) throws -> [UInt8] {
        guard headerKey.count == 32 && input.count == 0x400 else {
            throw Failure.cipher
        }
        let dataKey = Array(headerKey[0..<16])
        let tweakKey = Array(headerKey[16..<32])
        var result = [UInt8](repeating: 0, count: input.count)

        for sector in 0..<2 {
            var sectorNumber = [UInt8](repeating: 0, count: 16)
            sectorNumber[15] = UInt8(sector)
            var tweak = try aesBlock(sectorNumber, key: tweakKey, encrypt: true)
            for block in 0..<32 {
                let at = sector * 0x200 + block * 16
                var pre = [UInt8](repeating: 0, count: 16)
                for j in 0..<16 { pre[j] = input[at + j] ^ tweak[j] }
                let transformed = try aesBlock(pre, key: dataKey, encrypt: encrypt)
                for j in 0..<16 { result[at + j] = transformed[j] ^ tweak[j] }
                multiplyAlpha(&tweak)
            }
        }
        return result
    }

    private static func u64(_ b: [UInt8], at: Int) -> UInt64 {
        var value: UInt64 = 0
        for i in 0..<8 { value |= UInt64(b[at + i]) << (8 * i) }
        return value
    }

    /// Scans NCA entries in-place without copying/decrypting large game files.
    /// Only returns headers whose NCA2/NCA3 magic validates with the given key.
    static func scan(nsp: URL, index: NSPIndex, headerKey: [UInt8]) throws -> [NCAHeaderInfo] {
        let handle = try FileHandle(forReadingFrom: nsp)
        defer { try? handle.close() }
        var records: [NCAHeaderInfo] = []
        for entry in index.entries {
            guard entry.name.lowercased().hasSuffix(".nca"),
                  entry.length >= 0x400 else { continue }
            try handle.seek(toOffset: entry.offset)
            guard let bytes = try handle.read(upToCount: 0x400),
                  bytes.count == 0x400 else { continue }
            let plain = try cryptHeader([UInt8](bytes), headerKey: headerKey,
                                        encrypt: false)
            let magic = String(bytes: plain[0x200..<0x204], encoding: .ascii)
            guard magic == "NCA3" || magic == "NCA2" else { continue }
            records.append(NCAHeaderInfo(name: entry.name,
                                         programId: u64(plain, at: 0x210),
                                         contentType: plain[0x205]))
        }
        return records
    }
}
