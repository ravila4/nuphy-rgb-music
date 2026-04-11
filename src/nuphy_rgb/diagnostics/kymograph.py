"""Kymograph benchmark for music-reactive LED effects.

A kymograph is a space-time heatmap: one keyboard row along the x-axis,
time along the y-axis, color at each pixel. It collapses one spatial
dimension but preserves time, so motion appears as diagonal structure,
decay as fade, and wash-out as uniform bands.

Use for 1D-ish effects (waves, scrolls, feedback trails). For
2D/structural effects use ``contact_sheet`` instead.

Usage::

    uv run python -m nuphy_rgb.diagnostics.kymograph
    uv run python -m nuphy_rgb.diagnostics.kymograph "Polarity"
    uv run python -m nuphy_rgb.diagnostics.kymograph --start 30 --duration 30

Default staple: Bowie — Space Oddity 2015 Remaster, 0:00–1:00.
"""

from __future__ import annotations

import argparse
import math
import sys
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
from nuphy_rgb.effects.grid import ROWS  # noqa: E402

_KYMO_ROWS = [0, 2, 4]


def plot_kymograph(
    grids: np.ndarray,
    times: np.ndarray,
    effect_name: str,
    label: str,
    out_path: Path,
) -> None:
    if len(times) == 0:
        raise ValueError("plot_kymograph: empty time array")
    fig, axes = plt.subplots(1, 3, figsize=(18, 9))
    for ax_idx, row_idx in enumerate(_KYMO_ROWS):
        width = len(ROWS[row_idx])
        strip = grids[:, row_idx, :width, :]

        ax = axes[ax_idx]
        ax.imshow(strip, aspect="auto", origin="upper", interpolation="nearest")
        ax.set_xlabel("Column")
        ax.set_ylabel("Time")
        ax.set_title(f"Row {row_idx} ({width} keys)")

        tick_frames: list[int] = []
        tick_labels: list[str] = []
        for sec in range(int(math.floor(times[-1])) + 1):
            idx = int(np.argmin(np.abs(times - sec)))
            tick_frames.append(idx)
            tick_labels.append(f"{sec}s")
        ax.set_yticks(tick_frames)
        ax.set_yticklabels(tick_labels)

    fig.suptitle(f"{effect_name} — Kymograph — {label}", fontsize=13)
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
    out = out_dir / f"kymograph_{slug}.png"
    plot_kymograph(
        metrics["grids"], metrics["times"],
        effect.name,  # type: ignore[union-attr]
        label, out,
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Kymograph diagnostic for music-reactive LED effects",
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
