import AppKit
import SwiftUI

/// Per-effect slider window. Sidebar lists all effects; detail pane
/// renders the selected effect's params. Tuning is decoupled from
/// whichever effect is currently playing.
struct TuningWindow: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        NavigationSplitView {
            TuningSidebar()
                .navigationSplitViewColumnWidth(
                    min: 180, ideal: 200, max: 260,
                )
        } detail: {
            if let effect = appState.selectedEffectForTuning {
                TuningDetailPane(effect: effect)
            } else {
                ContentUnavailableView(
                    "Select an effect",
                    systemImage: "slider.horizontal.3",
                    description: Text("Pick an effect from the sidebar to tune."),
                )
            }
        }
        .frame(minWidth: 560, minHeight: 420)
        .onAppear { appState.openTuningWindow() }
        .onDisappear {
            // Return to menu-bar-only mode when the window closes so the
            // dock icon doesn't linger.
            NSApp.setActivationPolicy(.accessory)
        }
        .onChange(of: appState.selectedEffectForTuning) { _, newValue in
            guard let effect = newValue else { return }
            if appState.paramsByEffect[effect] == nil {
                appState.loadParams(for: effect)
            }
        }
    }
}
