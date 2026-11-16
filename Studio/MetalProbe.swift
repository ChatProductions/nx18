import Foundation
import Metal

/// Device-local Metal Shading Language compilation, with an offscreen GPU draw.
/// This demonstrates a compiler path without Apple's Windows Metal tools.
/// It is a capability check, NOT Switch shader translation or game rendering.
enum MetalProbe {
    enum Failure: LocalizedError {
        case noDevice, noFunction, noTexture, noQueue, noCommandBuffer, noEncoder, execution(String)
        var errorDescription: String? {
            switch self {
            case .noDevice: return "No Apple Metal device found."
            case .noFunction: return "MSL entry point was not found."
            case .noTexture: return "Could not allocate the render target."
            case .noQueue: return "Could not create Metal command queue."
            case .noCommandBuffer: return "Could not create Metal command buffer."
            case .noEncoder: return "Could not encode the render pass."
            case .execution(let reason): return "Metal command did not complete: " + reason
            }
        }
    }

    private static let msl = """
    #include <metal_stdlib>
    using namespace metal;
    vertex float4 nx18_vertex(uint id [[vertex_id]]) {
        float2 points[3] = {
            float2(-0.8, -0.8), float2(0.0, 0.8), float2(0.8, -0.8)
        };
        return float4(points[id], 0.0, 1.0);
    }
    fragment float4 nx18_fragment() {
        return float4(0.25, 0.5, 0.85, 1.0);
    }
    """

    static func run() throws -> String {
        guard let device = MTLCreateSystemDefaultDevice() else { throw Failure.noDevice }
        let shaderLibrary = try device.makeLibrary(source: msl, options: MTLCompileOptions())
        guard let vertex = shaderLibrary.makeFunction(name: "nx18_vertex"),
              let fragment = shaderLibrary.makeFunction(name: "nx18_fragment") else {
            throw Failure.noFunction
        }

        let config = MTLRenderPipelineDescriptor()
        config.vertexFunction = vertex
        config.fragmentFunction = fragment
        config.colorAttachments[0].pixelFormat = .bgra8Unorm
        let pipeline = try device.makeRenderPipelineState(descriptor: config)

        let descriptor = MTLTextureDescriptor.texture2DDescriptor(
            pixelFormat: .bgra8Unorm, width: 32, height: 32, mipmapped: false)
        descriptor.usage = [.renderTarget]
        guard let texture = device.makeTexture(descriptor: descriptor) else {
            throw Failure.noTexture
        }
        guard let queue = device.makeCommandQueue() else { throw Failure.noQueue }
        guard let command = queue.makeCommandBuffer() else { throw Failure.noCommandBuffer }

        let pass = MTLRenderPassDescriptor()
        pass.colorAttachments[0].texture = texture
        pass.colorAttachments[0].loadAction = .clear
        pass.colorAttachments[0].storeAction = .store
        pass.colorAttachments[0].clearColor = MTLClearColor(
            red: 0, green: 0, blue: 0, alpha: 1)
        guard let encoder = command.makeRenderCommandEncoder(descriptor: pass) else {
            throw Failure.noEncoder
        }
        encoder.setRenderPipelineState(pipeline)
        encoder.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
        encoder.endEncoding()
        command.commit()
        command.waitUntilCompleted()
        guard command.status == .completed else {
            throw Failure.execution(command.error?.localizedDescription ?? "unknown GPU error")
        }
        let apple7 = device.supportsFamily(.apple7)
        return "PASS: MSL compiled on device and offscreen triangle completed on " +
               device.name + ". Apple GPU family 7+: " + String(apple7) +
               ". This does not verify NVN translation or game compatibility."
    }
}
