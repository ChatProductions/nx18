// SwiftUI document picker/inspector on the existing iOS17 Metal3 UIKit host.
// Game-specific, prelinked native packages retain the original gameplay path.
import UIKit
import SwiftUI

@_cdecl("nx18_show_nsp_studio")
public func nx18ShowNSPStudio(_ viewController: UnsafeMutableRawPointer?) {
    guard let viewController = viewController else { return }
    let parent = Unmanaged<UIViewController>.fromOpaque(viewController).takeUnretainedValue()
    let controller = UIHostingController(rootView: StudioView())
    controller.modalPresentationStyle = .fullScreen
    parent.present(controller, animated: false)
}


// The guaranteed launch UI for a game-free NX18 shell.
// Ownership is deliberately transferred to the UIKit scene root.
@_cdecl("nx18_make_nsp_studio_root")
public func nx18MakeNSPStudioRoot() -> UnsafeMutableRawPointer {
    let controller = UIHostingController(rootView: StudioView())
    return Unmanaged.passRetained(controller).toOpaque()
}
