import Foundation

/// CPU fallback for GPUs that cannot sample Switch/DX BC-compressed textures.
/// Decoder output is row-major, tightly packed RGBA8. No Metal dependency.
/// Implemented: BC1 RGB/DXT1 (including 1-bit alpha), BC3/DXT5.
/// TODO: BC2, BC4/5, BC6H, BC7, swizzle, mipmaps and GPU upload integration.
enum BCDecode {
    enum Failure: LocalizedError {
        case dimensions, byteCount
        var errorDescription: String? {
            switch self {
            case .dimensions: return "Invalid dimensions or excessive output allocation."
            case .byteCount: return "BC-compressed byte count does not match the texture dimensions."
            }
        }
    }

    private struct Pixel {
        var r: UInt8, g: UInt8, b: UInt8, a: UInt8
    }

    private static func color565(_ v: UInt16) -> Pixel {
        let r = Int((v >> 11) & 31)
        let g = Int((v >> 5) & 63)
        let b = Int(v & 31)
        return Pixel(r: UInt8(r * 255 / 31),
                     g: UInt8(g * 255 / 63),
                     b: UInt8(b * 255 / 31),
                     a: 255)
    }

    private static func interpolate(_ a: Pixel, _ b: Pixel,
                                    wa: Int, wb: Int, divisor: Int) -> Pixel {
        Pixel(r: UInt8((Int(a.r) * wa + Int(b.r) * wb) / divisor),
              g: UInt8((Int(a.g) * wa + Int(b.g) * wb) / divisor),
              b: UInt8((Int(a.b) * wa + Int(b.b) * wb) / divisor),
              a: 255)
    }

    private static func colorPalette(_ input: [UInt8], at: Int,
                                     forceFour: Bool) -> [Pixel] {
        let c0 = UInt16(input[at]) | (UInt16(input[at + 1]) << 8)
        let c1 = UInt16(input[at + 2]) | (UInt16(input[at + 3]) << 8)
        let a = color565(c0), b = color565(c1)
        if forceFour || c0 > c1 {
            return [a, b,
                    interpolate(a, b, wa: 2, wb: 1, divisor: 3),
                    interpolate(a, b, wa: 1, wb: 2, divisor: 3)]
        }
        return [a, b,
                interpolate(a, b, wa: 1, wb: 1, divisor: 2),
                Pixel(r: 0, g: 0, b: 0, a: 0)]
    }

    private static func alphaPalette(_ input: [UInt8], at: Int) -> [UInt8] {
        let a = Int(input[at]), b = Int(input[at + 1])
        if a > b {
            return [UInt8(a), UInt8(b),
                    UInt8((6 * a + b) / 7), UInt8((5 * a + 2 * b) / 7),
                    UInt8((4 * a + 3 * b) / 7), UInt8((3 * a + 4 * b) / 7),
                    UInt8((2 * a + 5 * b) / 7), UInt8((a + 6 * b) / 7)]
        }
        return [UInt8(a), UInt8(b),
                UInt8((4 * a + b) / 5), UInt8((3 * a + 2 * b) / 5),
                UInt8((2 * a + 3 * b) / 5), UInt8((a + 4 * b) / 5),
                0, 255]
    }

    /// Format is "BC1" or "BC3", in standard 4x4 block order.
    static func decode(_ input: [UInt8], width: Int, height: Int,
                       format: String) throws -> [UInt8] {
        let blockBytes: Int
        switch format {
        case "BC1": blockBytes = 8
        case "BC3": blockBytes = 16
        default: throw Failure.byteCount
        }
        // Protect the A15's 4 GiB RAM from pathological dimensions. 4096^2 = 64 MiB RGBA8.
        guard width > 0, height > 0, width <= 4096, height <= 4096,
              width * height <= 16_777_216 else {
            throw Failure.dimensions
        }
        let cols = (width + 3) / 4
        let rows = (height + 3) / 4
        guard input.count == cols * rows * blockBytes else {
            throw Failure.byteCount
        }
        var output = [UInt8](repeating: 0, count: width * height * 4)

        for by in 0..<rows {
            for bx in 0..<cols {
                let at = (by * cols + bx) * blockBytes
                let colorStart = at + (blockBytes == 16 ? 8 : 0)
                let colors = colorPalette(input, at: colorStart,
                                          forceFour: blockBytes == 16)
                let selector = UInt32(input[colorStart + 4]) |
                               (UInt32(input[colorStart + 5]) << 8) |
                               (UInt32(input[colorStart + 6]) << 16) |
                               (UInt32(input[colorStart + 7]) << 24)
                let alphas = blockBytes == 16 ? alphaPalette(input, at: at) : []
                var alphaSelector: UInt64 = 0
                if blockBytes == 16 {
                    for j in 0..<6 {
                        alphaSelector |= UInt64(input[at + 2 + j]) << (8 * j)
                    }
                }

                for py in 0..<4 {
                    for px in 0..<4 {
                        let x = bx * 4 + px, y = by * 4 + py
                        if x >= width || y >= height { continue }
                        let pos = py * 4 + px
                        let code = Int((selector >> (2 * pos)) & 3)
                        var pixel = colors[code]
                        if blockBytes == 16 {
                            let ai = Int((alphaSelector >> (3 * pos)) & 7)
                            pixel.a = alphas[ai]
                        }
                        let outAt = (y * width + x) * 4
                        output[outAt] = pixel.r
                        output[outAt + 1] = pixel.g
                        output[outAt + 2] = pixel.b
                        output[outAt + 3] = pixel.a
                    }
                }
            }
        }
        return output
    }
}
