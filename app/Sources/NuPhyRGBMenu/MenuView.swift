import SwiftUI

struct MenuView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if !appState.isConnected {
            Text("Not Connected")
                .foregroundStyle(.secondary)
            Divider()
        }

        // Effects submenu
        if !appState.effects.isEmpty {
            Menu("Effects") {
                ForEach(appState.effects, id: \.self) { name in
                    Button {
                        appState.selectEffect(name)
                    } label: {
                        HStack {
                            Image(systemName: appState.activeEffect == name ? "checkmark" : "")
                                .frame(width: 16)
                            Text(name)
                        }
                    }
                }
            }
        }

        // Sidelights submenu
        if !appState.sidelights.isEmpty {
            Menu("Side LEDs") {
                ForEach(appState.sidelights, id: \.self) { name in
                    Button {
                        appState.selectSidelight(name)
                    } label: {
                        HStack {
                            Image(systemName: appState.activeSidelight == name ? "checkmark" : "")
                                .frame(width: 16)
                            Text(name)
                        }
                    }
                }
            }
            Divider()
        }

        // Daemon control
        if appState.isConnected {
            Button(appState.isPaused ? "Resume" : "Pause") {
                appState.togglePause()
            }
        } else {
            Button("Start Daemon") {
                appState.startDaemon()
            }
        }

        if appState.isConnected && !appState.effects.isEmpty {
            Button("Settings…") {
                openWindow(id: "tuning")
                // MenuBarExtra apps use accessory activation policy; openWindow
                // alone places the window behind foreground apps. Flip the
                // policy, raise the window, then flip back on close.
                NSApp.setActivationPolicy(.regular)
                NSApp.activate(ignoringOtherApps: true)
                DispatchQueue.main.async {
                    if let window = NSApp.windows.first(where: { $0.identifier?.rawValue == "tuning" }) {
                        window.makeKeyAndOrderFront(nil)
                    }
                }
            }
        }

        Divider()

        Button("About NuPhy RGB") {
            showAboutPanel()
        }

        Button("Quit") {
            Task {
                await appState.quitApp()
            }
        }
        .keyboardShortcut("q")
    }

    /// Show the standard macOS About panel, foregrounding it properly
    /// for a menu-bar-only app. Accessory apps can't raise windows on
    /// top of others, so flip to regular activation policy, show the
    /// panel, then flip back when it closes.
    private func showAboutPanel() {
        let credits = NSMutableAttributedString()
        credits.append(NSAttributedString(
            string: "Music-reactive RGB for NuPhy keyboards\n\n",
            attributes: [.font: NSFont.systemFont(ofSize: 11)],
        ))
        credits.append(NSAttributedString(
            string: "GitHub",
            attributes: [
                .font: NSFont.systemFont(ofSize: 11),
                .link: URL(string: "https://github.com/ravila4/nuphy-rgb-music")!,
            ],
        ))
        credits.append(NSAttributedString(
            string: "  ·  ",
            attributes: [.font: NSFont.systemFont(ofSize: 11)],
        ))
        credits.append(NSAttributedString(
            string: "Support on Ko-fi",
            attributes: [
                .font: NSFont.systemFont(ofSize: 11),
                .link: URL(string: "https://ko-fi.com/ravila4")!,
            ],
        ))

        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "NuPhy RGB",
            .applicationIcon: NSApplication.shared.applicationIconImage as Any,
            .version: "",
            .credits: credits,
        ])

        // Find the panel (created synchronously by orderFrontStandardAboutPanel)
        // and flip back to accessory when it closes.
        DispatchQueue.main.async {
            guard let panel = NSApp.windows.first(where: { $0.title.contains("NuPhy RGB") && $0.isVisible }) else {
                return
            }
            panel.makeKeyAndOrderFront(nil)
            var observer: NSObjectProtocol?
            observer = NotificationCenter.default.addObserver(
                forName: NSWindow.willCloseNotification,
                object: panel,
                queue: .main,
            ) { _ in
                NSApp.setActivationPolicy(.accessory)
                if let obs = observer {
                    NotificationCenter.default.removeObserver(obs)
                }
            }
        }
    }
}
