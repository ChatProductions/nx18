import Foundation
import UIKit
import UniformTypeIdentifiers

/// A direct UIKit document picker. NX18 hosts SwiftUI in UIKit's SceneDelegate;
/// SwiftUI .fileImporter can fail silently in that arrangement on iOS 18.
/// File selection never grants execution privileges or bypasses iOS signing.
@MainActor
enum NX18DocumentPicker {
    private final class PickerController: UIDocumentPickerViewController, UIDocumentPickerDelegate {
        private let didSelect: (URL) -> Void
        private let didCancel: () -> Void

        init(didSelect: @escaping (URL) -> Void,
             didCancel: @escaping () -> Void) {
            self.didSelect = didSelect
            self.didCancel = didCancel
            // .item includes NSP archives whose imported UTType is dynamic
            // or whose extension the file provider does not recognize.
            // Opening in place avoids duplicating multi-GB game packages.
            super.init(forOpeningContentTypes: [.item], asCopy: false)
            allowsMultipleSelection = false
            shouldShowFileExtensions = true
            delegate = self
            modalPresentationStyle = .formSheet
        }

        @available(*, unavailable)
        required init?(coder: NSCoder) {
            fatalError("Use init(didSelect:didCancel:)")
        }

        func documentPicker(_ controller: UIDocumentPickerViewController,
                            didPickDocumentsAt urls: [URL]) {
            guard let first = urls.first else { didCancel(); return }
            didSelect(first)
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            didCancel()
        }
    }

    /// Returns an immediate, actionable presentation error instead of a dead
    /// button. Picker callbacks and processing remain on the main actor.
    static func open(didSelect: @escaping (URL) -> Void,
                     didCancel: @escaping () -> Void,
                     didFail: @escaping (String) -> Void) {
        let windows = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .filter { $0.activationState == .foregroundActive }
            .flatMap { $0.windows }
        guard let root = (windows.first(where: { $0.isKeyWindow })
                          ?? windows.first)?.rootViewController else {
            didFail("No active iOS window. Use the NSP-Inbox below.")
            return
        }
        var presenter = root
        while let presented = presenter.presentedViewController {
            presenter = presented
        }
        guard !presenter.isBeingDismissed else {
            didFail("A dialog is closing. Use the NSP-Inbox below or retry.")
            return
        }
        let picker = PickerController(didSelect: didSelect, didCancel: didCancel)
        presenter.present(picker, animated: true)
    }
}
