import SwiftUI

/// One labelled slider bound to a `ParamSchema` on `AppState`.
struct ParamSliderRow: View {
    let effect: String
    let param: ParamSchema
    @Environment(AppState.self) private var appState

    var body: some View {
        let binding = Binding<Double>(
            get: { param.value },
            set: { newValue in
                appState.setParam(
                    effect: effect,
                    name: param.name,
                    value: newValue,
                )
            },
        )

        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(param.name)
                    .font(.system(.body, design: .monospaced))
                Spacer()
                Text(String(format: "%.3f", param.value))
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            Slider(value: binding, in: param.min...param.max)
            if !param.description.isEmpty {
                Text(param.description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
