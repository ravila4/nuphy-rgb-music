import AppKit
import IOKit.hid
import os
import SwiftUI

private let logger = Logger(subsystem: "com.nuphy-rgb.menu", category: "Permissions")

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Bring app to front so permission alerts are visible
        NSApp.activate(ignoringOtherApps: true)

        // Check permissions before the daemon starts (AppState.init triggers daemon launch)
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(500))
            checkPermissions()
        }
    }

    private func checkPermissions() {
        // Screen & System Audio Recording: no reliable preflight API for Process Tap
        // audio capture (CGPreflightScreenCaptureAccess checks screen capture, not audio).
        // Prompt once on first launch; the daemon handles the failure case.
        let promptedKey = "hasPromptedForScreenRecording"
        if !UserDefaults.standard.bool(forKey: promptedKey) {
            UserDefaults.standard.set(true, forKey: promptedKey)
            promptForPermission(
                name: "Screen & System Audio Recording",
                reason: "to capture system audio for music-reactive effects",
                pane: "Privacy_ScreenCapture"
            )
        }

        // Input Monitoring: IOHIDCheckAccess reliably detects the current state,
        // including stale CDHash grants. Check every launch.
        let hidAccess = IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)
        let hasInputMonitoring = hidAccess == kIOHIDAccessTypeGranted
        logger.warning("permissions: inputMonitoring=\(hasInputMonitoring) (raw=\(hidAccess.rawValue))")

        if !hasInputMonitoring {
            promptForPermission(
                name: "Input Monitoring",
                reason: "to send RGB data to your keyboard via USB",
                pane: "Privacy_ListenEvent"
            )
        }
    }

    private func promptForPermission(name: String, reason: String, pane: String) {
        let alert = NSAlert()
        alert.icon = NSApplication.shared.applicationIconImage
        alert.messageText = "\(name) Required"
        alert.informativeText = """
            NuPhy RGB needs "\(name)" \(reason).\n\n\
            After granting permission in System Settings, \
            restart NuPhy RGB for it to take effect.
            """
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Open System Settings")
        alert.addButton(withTitle: "Later")

        if alert.runModal() == .alertFirstButtonReturn {
            openSystemSettings(pane: pane)
        }
    }

    private func openSystemSettings(pane: String) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") {
            NSWorkspace.shared.open(url)
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
