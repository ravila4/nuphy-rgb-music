import SwiftUI

/// Right column of the tuning window: slider list + revert button.
/// The effect name is shown via `navigationTitle`; the sidebar dot
/// already indicates which effect is playing.
struct TuningDetailPane: View {
    let effect: String
    @Environment(AppState.self) private var appState

    var body: some View {
        let params = appState.paramsByEffect[effect] ?? []

        Group {
            if params.isEmpty {
                ContentUnavailableView(
                    "No tunable parameters",
                    systemImage: "slider.horizontal.below.rectangle",
                    description: Text("This effect does not expose any knobs."),
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                VStack(spacing: 0) {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 20) {
                            ForEach(params) { param in
                                ParamSliderRow(effect: effect, param: param)
                            }
                        }
                        .padding(20)
                    }

                    Divider()

                    HStack {
                        Spacer()
                        Button("Revert to defaults") {
                            appState.resetParams(effect: effect)
                        }
                        .disabled(params.allSatisfy(\.isAtDefault))
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                }
            }
        }
        .navigationTitle(effect)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Play", systemImage: "play.fill") {
                    appState.selectEffect(effect)
                }
                .disabled(effect == appState.activeEffect)
                .help(effect == appState.activeEffect ? "Already playing" : "Play \(effect)")
            }
        }
    }
}
