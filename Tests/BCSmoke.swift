import Foundation

@main
struct BCSmoke {
    static func main() throws {
        // BC1 palette index 0 = RGB565 red, 16 pixels.
        let solidRed: [UInt8] = [0x00, 0xf8, 0, 0, 0, 0, 0, 0]
        let red = try BCDecode.decode(solidRed, width: 4, height: 4, format: "BC1")
        precondition(red.count == 64)
        for i in stride(from: 0, to: red.count, by: 4) {
            precondition(Array(red[i..<(i + 4)]) == [255, 0, 0, 255])
        }

        // BC1: c0 <= c1, index 3 must be transparent.
        let transparent: [UInt8] = [0, 0, 0, 0xf8, 255, 255, 255, 255]
        let trans = try BCDecode.decode(transparent, width: 4, height: 4, format: "BC1")
        precondition(trans[3] == 0)

        // BC3: 128 alpha everywhere, all pixels select solid-red color.
        let bc3: [UInt8] = [128, 0, 0, 0, 0, 0, 0, 0] + solidRed
        let semi = try BCDecode.decode(bc3, width: 4, height: 4, format: "BC3")
        precondition(Array(semi[0..<4]) == [255, 0, 0, 128])
        precondition(Array(semi[60..<64]) == [255, 0, 0, 128])

        // Partial edge blocks: 5x5 image consists of 4 complete BC1 blocks.
        let clipped = try BCDecode.decode(solidRed + solidRed + solidRed + solidRed,
                                          width: 5, height: 5, format: "BC1")
        precondition(clipped.count == 100)
        precondition(Array(clipped[96..<100]) == [255, 0, 0, 255])

        // Fail-closed allocation/input length.
        do {
            _ = try BCDecode.decode(solidRed, width: 8, height: 8, format: "BC1")
            fatalError("Truncated BC1 input was accepted")
        } catch BCDecode.Failure.byteCount { }
        do {
            _ = try BCDecode.decode(solidRed, width: 5000, height: 1, format: "BC1")
            fatalError("Invalid dimensions were accepted")
        } catch BCDecode.Failure.dimensions { }
        print("PASS: BC1 opaque/transparent, BC3 alpha, clipping and safety checks")
    }
}
