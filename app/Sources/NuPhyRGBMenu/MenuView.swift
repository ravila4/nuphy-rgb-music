import SwiftUI

struct MenuView: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        if !appState.isConnected {
            Text("Not Connected")
                .foregroundStyle(.secondary)
            Divider()
        }

        // Effects
        if !appState.effects.isEmpty {
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
            Divider()
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
            Button("Quit Daemon") {
                appState.stopDaemon()
            }
        } else {
            Button("Start Daemon") {
                appState.startDaemon()
            }
        }

        Divider()

        Button("Quit") {
            NSApplication.shared.terminate(nil)
        }
        .keyboardShortcut("q")
    }
}
