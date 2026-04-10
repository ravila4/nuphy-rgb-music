import AppKit
import CoreGraphics
import IOKit.hid
import os
import SwiftUI

private let logger = Logger(subsystem: "com.nuphy-rgb.menu", category: "Permissions")

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Check permissions before the daemon starts (AppState.init triggers daemon launch)
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(500))
            checkPermissions()
        }
    }

    private func checkPermissions() {
        let hasScreenRecording = CGPreflightScreenCaptureAccess()
        let hidAccess = IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)
        let hasInputMonitoring = hidAccess == kIOHIDAccessTypeGranted

        logger.warning("permissions: screenRecording=\(hasScreenRecording) inputMonitoring=\(hasInputMonitoring) (raw=\(hidAccess.rawValue))")

        if hasScreenRecording && hasInputMonitoring { return }

        // Build a message describing what's missing
        var missing: [String] = []
        if !hasScreenRecording { missing.append("Screen & System Audio Recording") }
        if !hasInputMonitoring { missing.append("Input Monitoring") }

        let alert = NSAlert()
        alert.messageText = "Permissions Required"
        alert.informativeText = """
            NuPhy RGB needs the following permissions to control \
            your keyboard:\n\n\
            \(missing.map { "  \u{2022} \($0)" }.joined(separator: "\n"))\n\n\
            After granting permissions in System Settings, \
            restart NuPhy RGB for them to take effect.
            """
        alert.alertStyle = .warning

        // Open the most relevant pane first
        if !hasScreenRecording {
            alert.addButton(withTitle: "Open Screen Recording Settings")
        }
        if !hasInputMonitoring {
            alert.addButton(withTitle: "Open Input Monitoring Settings")
        }
        alert.addButton(withTitle: "Later")

        let response = alert.runModal()

        if response == .alertFirstButtonReturn {
            if !hasScreenRecording {
                openSystemSettings(pane: "Privacy_ScreenCapture")
            } else {
                openSystemSettings(pane: "Privacy_ListenEvent")
            }
        } else if response == .alertSecondButtonReturn && !hasScreenRecording && !hasInputMonitoring {
            // Second button when both are missing = Input Monitoring
            openSystemSettings(pane: "Privacy_ListenEvent")
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
