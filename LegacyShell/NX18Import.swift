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
