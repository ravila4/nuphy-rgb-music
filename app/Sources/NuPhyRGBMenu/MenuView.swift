import SwiftUI

struct MenuView: View {
    @Environment(AppState.self) private var appState

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

        Divider()

        Button("About NuPhy RGB") {
            let credits = NSMutableAttributedString()
            credits.append(NSAttributedString(
                string: "Music-reactive RGB for NuPhy keyboards\n\n",
                attributes: [.font: NSFont.systemFont(ofSize: 11)]
            ))
            credits.append(NSAttributedString(
                string: "Support on Ko-fi",
                attributes: [
                    .font: NSFont.systemFont(ofSize: 11),
                    .link: URL(string: "https://ko-fi.com/ravila4")!,
                ]
            ))

            NSApplication.shared.orderFrontStandardAboutPanel(options: [
                .applicationName: "NuPhy RGB",
                .applicationIcon: NSApplication.shared.applicationIconImage as Any,
                .version: "",
                .credits: credits,
            ])
            NSApplication.shared.activate(ignoringOtherApps: true)
        }

        Button("Quit") {
            Task {
                await appState.quitApp()
            }
        }
        .keyboardShortcut("q")
    }
}
