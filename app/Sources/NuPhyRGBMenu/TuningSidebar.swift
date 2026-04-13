import SwiftUI

/// Left column of the tuning window: list of all effects, with a dot
/// marking whichever one is currently playing.
struct TuningSidebar: View {
    @Environment(AppState.self) private var appState

    var body: some View {
        @Bindable var state = appState
        List(selection: $state.selectedEffectForTuning) {
            Section("Effects") {
                ForEach(state.effects, id: \.self) { name in
                    TuningSidebarRow(
                        name: name,
                        description: state.effectDescriptions[name] ?? "",
                        isPlaying: name == state.activeEffect,
                    )
                    .tag(name)
                }
            }
        }
    }
}

private struct TuningSidebarRow: View {
    let name: String
    let description: String
    let isPlaying: Bool

    var body: some View {
        HStack {
            Text(name)
            Spacer()
            if isPlaying {
                Circle()
                    .fill(Color.accentColor)
                    .frame(width: 6, height: 6)
            }
        }
        .contentShape(Rectangle())
        .help(description.isEmpty ? name : description)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            isPlaying ? "\(name), currently playing" : name,
        )
        .accessibilityHint(description)
    }
}
