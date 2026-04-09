import AppKit

// Pure AppKit bootstrap — no SwiftUI App protocol.
// SwiftUI's @main App lifecycle doesn't properly register
// with the window server when built via SPM.

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    // Must be a stored property — NSStatusItem is released
    // (and the icon vanishes) if it goes out of scope.
    private var statusItem: NSStatusItem!

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(
            withLength: NSStatusItem.variableLength
        )

        if let button = statusItem.button {
            button.image = NSImage(
                systemSymbolName: "star.fill",
                accessibilityDescription: "NuPhy RGB"
            )
        }

        let menu = NSMenu()
        menu.addItem(
            NSMenuItem(
                title: "Quit",
                action: #selector(NSApplication.terminate(_:)),
                keyEquivalent: "q"
            )
        )
        statusItem.menu = menu

        print("[App] status item created")
    }
}

// Entry point — manual NSApplication bootstrap
@main
struct NuPhyRGBMenuApp {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
    }
}
