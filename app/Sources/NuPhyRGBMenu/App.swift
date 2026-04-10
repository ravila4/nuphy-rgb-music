import AppKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Hello World window
        window = NSWindow(
            contentRect: NSRect(x: 200, y: 200, width: 400, height: 200),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "NuPhy RGB"

        let label = NSTextField(labelWithString: "Hello from NuPhy RGB!")
        label.font = NSFont.systemFont(ofSize: 24)
        label.alignment = .center
        label.frame = NSRect(x: 50, y: 80, width: 300, height: 40)
        window.contentView?.addSubview(label)

        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        // Delay permission prompt so it doesn't block daemon connection
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [self] in
            promptForAudioPermissionIfNeeded()
        }
    }

    private func promptForAudioPermissionIfNeeded() {
        guard !CGPreflightScreenCaptureAccess() else { return }

        let alert = NSAlert()
        alert.messageText = "Screen & System Audio Recording"
        alert.informativeText = """
            NuPhy RGB needs "Screen & System Audio Recording" permission \
            to capture system audio for music-reactive effects.

            Please add this app (NuPhy RGB) in System Settings, then \
            restart the app.
            """
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Open System Settings")
        alert.addButton(withTitle: "Later")

        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture") {
                NSWorkspace.shared.open(url)
            }
        }
    }
}

@main
struct NuPhyRGBMenuApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @State private var appState = AppState()

    var body: some Scene {
        MenuBarExtra("NuPhy RGB", systemImage: appState.statusIcon) {
            MenuView()
                .environment(appState)
        }
    }
}
