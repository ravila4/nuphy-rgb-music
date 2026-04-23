"""Time series diagnostic for music-reactive LED effects.

Five-panel plot auditing an effect's *response* to the audio:

1. Audio input (bass / mids / highs with beat markers)
2. Mean LED brightness
3. Spatial variance (std dev of per-LED brightness)
4. Frame-to-frame delta
5. Chroma argmax (which pitch class is driving the effect)

Use to answer "is the effect responding at all?" and "is it responding
to the right thing?" rather than "does it look good?". For appearance,
use ``contact_sheet`` or ``kymograph``.

Usage::

    uv run python -m nuphy_rgb.diagnostics.timeseries
    uv run python -m nuphy_rgb.diagnostics.timeseries "Polarity"
    uv run python -m nuphy_rgb.diagnostics.timeseries --start 30 --duration 30

Default staple: Bowie — Space Oddity 2015 Remaster, 0:00–1:00.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from nuphy_rgb.audio import AudioFrame  # noqa: E402
from nuphy_rgb.diagnostics._common import (  # noqa: E402
    add_common_arguments,
    collect_metrics,
    effects_from_args,
    prepare_from_args,
    run_pipeline,
)

_PITCH_LABELS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def plot_timeseries(
    metrics: dict[str, np.ndarray],
    effect_name: str,
    label: str,
    out_path: Path,
) -> None:
    fig, axes = plt.subplots(5, 1, figsize=(18, 14), sharex=True)
    t = metrics["times"]

    # Panel 1 — audio input
    ax = axes[0]
    ax.plot(t, metrics["bass"], label="bass", color="red", alpha=0.8, linewidth=0.8)
    ax.plot(t, metrics["mids"], label="mids", color="green", alpha=0.8, linewidth=0.8)
    ax.plot(t, metrics["highs"], label="highs", color="blue", alpha=0.8, linewidth=0.8)
    beat_times = t[metrics["beats"]]
    if len(beat_times):
        ax.vlines(
            beat_times, 0, 1.0,
            colors="orange", alpha=0.5, linewidth=1.0, label="beats",
        )
    ax.set_ylabel("Energy")
    ax.set_ylim(0, 1.2)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title("Audio Input")

    # Panel 2 — mean brightness
    ax = axes[1]
    ax.plot(t, metrics["mean_brightness"], color="goldenrod", linewidth=0.8)
    ax.set_ylabel("Mean Brightness")
    ax.set_ylim(0, max(0.05, float(np.max(metrics["mean_brightness"])) * 1.2))
    ax.set_title("Mean LED Brightness (84 LEDs)")

    # Panel 3 — spatial variance
    ax = axes[2]
    ax.plot(t, metrics["spatial_variance"], color="purple", linewidth=0.8)
    ax.set_ylabel("Std Dev")
    ax.set_ylim(0, max(0.02, float(np.max(metrics["spatial_variance"])) * 1.2))
    ax.set_title("Spatial Variance")

    # Panel 4 — frame delta
    ax = axes[3]
    ax.plot(t, metrics["frame_delta"], color="teal", linewidth=0.8)
    ax.set_ylabel("Mean |delta|")
    ax.set_ylim(0, max(0.02, float(np.max(metrics["frame_delta"])) * 1.2))
    ax.set_title("Frame-to-Frame Delta")

    # Panel 5 — chroma argmax
    ax = axes[4]
    valid = metrics["chroma_argmax"] >= 0
    ax.scatter(
        t[valid], metrics["chroma_argmax"][valid],
        c=metrics["chroma_peak"][valid], cmap="viridis", s=6, marker="o",
    )
    ax.set_ylabel("Chroma argmax")
    ax.set_ylim(-0.5, 11.5)
    ax.set_yticks(list(range(12)))
    ax.set_yticklabels(_PITCH_LABELS)
    ax.set_xlabel("Time (seconds)")
    ax.set_title("Chroma argmax (pitch class)")

    fig.suptitle(f"{effect_name} — Time Series — {label}", fontsize=13)
    plt.tight_layout()
    plt.savefig(out_path, dpi=130)
    plt.close()


def run_for_effect(
    effect: object,
    frames: list[AudioFrame],
    label: str,
    out_dir: Path,
) -> Path:
    metrics = collect_metrics(effect, frames)
    slug = effect.name.lower().replace(" ", "_")  # type: ignore[union-attr]
    out = out_dir / f"timeseries_{slug}.png"
    plot_timeseries(
        metrics,
        effect.name,  # type: ignore[union-attr]
        label, out,
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Time series diagnostic for music-reactive LED effects",
    )
    parser.add_argument(
        "effect", nargs="?", default=None,
        help='Effect name (default: all effects)',
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Render every effect (same as omitting <effect>)",
    )
    add_common_arguments(parser)
    args = parser.parse_args()

    samples, label = prepare_from_args(args)
    for cls in effects_from_args(args):
        frames = run_pipeline(samples)
        if not frames:
            print("  ! No frames generated (window too short?)")
            continue
        try:
            out = run_for_effect(cls(), frames, label, args.out_dir)
            print(f"  {cls.name:<22} → {out}")
        except Exception as exc:
            print(f"  {cls.name:<22} ! failed: {exc}")


if __name__ == "__main__":
    main()
