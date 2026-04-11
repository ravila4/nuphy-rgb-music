"""Contact sheet benchmark for music-reactive LED effects.

Unlike kymographs (which collapse one spatial axis), a contact sheet
keeps the actual keyboard shape at each sampled timestamp, so effects
with real 2D structure stay legible.

Each tile is drawn with the Air75 V2 physical key geometry from
``diagnostics.geometry`` — wide Backspace, 6.25u Space, stepped
modifiers, arrow cluster — so the sheet previews what the effect will
look like on actual hardware, not an abstract 6x16 matrix.

Use for 2D / structural effects (Polarity, Mycelium, Navier-Stokes).
For waves / scrolls / feedback trails, use ``kymograph`` instead.

Usage::

    uv run python -m nuphy_rgb.diagnostics.contact_sheet
    uv run python -m nuphy_rgb.diagnostics.contact_sheet "Aurora"
    uv run python -m nuphy_rgb.diagnostics.contact_sheet --all
    uv run python -m nuphy_rgb.diagnostics.contact_sheet --start 30 --duration 30

Default staple: Bowie — Space Oddity 2015 Remaster, 0:00–1:00.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
import numpy as np  # noqa: E402

from nuphy_rgb.audio import AudioFrame  # noqa: E402
from nuphy_rgb.diagnostics._common import (  # noqa: E402
    add_common_arguments,
    effects_from_args,
    prepare_from_args,
    render_effect_at_samples,
    run_pipeline,
)
from nuphy_rgb.diagnostics.geometry import (  # noqa: E402
    BOARD_H_U,
    BOARD_W_U,
    KEY_RECTS,
)

DEFAULT_TILES = 30
DEFAULT_COLS = 6


def _sample_times(start: float, duration: float, n_tiles: int) -> list[float]:
    """Pick n_tiles timestamps as interior midpoints of a uniform partition.

    Returned in local audio-position coordinates (0..duration), matching
    what ``run_pipeline`` stamps on each frame.
    """
    step = duration / n_tiles
    return [step * (i + 0.5) for i in range(n_tiles)]


def _draw_keyboard(ax: plt.Axes, leds: np.ndarray) -> None:
    """Draw the 84-key board into *ax* with real key geometry."""
    ax.set_xlim(-0.1, BOARD_W_U + 0.1)
    ax.set_ylim(BOARD_H_U + 0.1, -0.1)  # flipped: y grows downward
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    pad = 0.06
    radius = 0.12

    for rect in KEY_RECTS:
        r, g, b = leds[rect.led]
        color = (r / 255.0, g / 255.0, b / 255.0)
        x = rect.x_u + pad / 2
        y = rect.y_u + pad / 2
        w = rect.w_u - pad
        h = rect.h_u - pad
        patch = FancyBboxPatch(
            (x, y), w, h,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            linewidth=0.3,
            edgecolor=(0.25, 0.25, 0.25),
            facecolor=color,
        )
        ax.add_patch(patch)


def plot_contact_sheet(
    snapshots: list[np.ndarray],
    displayed_times: list[float],
    effect_name: str,
    label: str,
    out_path: Path,
    cols: int = DEFAULT_COLS,
) -> None:
    n = len(snapshots)
    rows = (n + cols - 1) // cols
    tile_w = 2.6
    tile_h = tile_w * (BOARD_H_U / BOARD_W_U) + 0.25

    fig, axes = plt.subplots(
        rows, cols,
        figsize=(tile_w * cols, tile_h * rows + 0.8),
        squeeze=False,
        gridspec_kw={"hspace": 0.35, "wspace": 0.08},
    )
    fig.patch.set_facecolor("#111111")

    for i in range(rows * cols):
        ax = axes[i // cols][i % cols]
        ax.set_facecolor("#111111")
        if i >= n:
            ax.axis("off")
            continue
        _draw_keyboard(ax, snapshots[i])
        ax.set_title(
            f"t = {displayed_times[i]:5.1f}s",
            fontsize=9, color="#cccccc", pad=4,
        )

    fig.suptitle(
        f"{effect_name}  —  {label}",
        fontsize=13, color="#eeeeee", y=0.995,
    )
    plt.savefig(out_path, dpi=140, facecolor=fig.get_facecolor())
    plt.close()


def run_for_effect(
    effect: object,
    frames: list[AudioFrame],
    sample_times_local: list[float],
    label: str,
    out_dir: Path,
    cols: int = DEFAULT_COLS,
) -> Path:
    snapshots, displayed = render_effect_at_samples(
        effect, frames, sample_times_local
    )
    if not snapshots:
        raise RuntimeError("No snapshots collected — empty frame list?")

    slug = effect.name.lower().replace(" ", "_")  # type: ignore[union-attr]
    out = out_dir / f"contact_{slug}.png"
    plot_contact_sheet(
        snapshots, displayed,
        effect.name,  # type: ignore[union-attr]
        label, out, cols=cols,
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Contact sheet benchmark for music-reactive LED effects",
    )
    parser.add_argument(
        "effect", nargs="?", default=None,
        help="Effect name (default: all effects)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Render every effect (same as omitting <effect>)",
    )
    parser.add_argument(
        "--tiles", type=int, default=DEFAULT_TILES,
        help=f"Number of snapshots (default: {DEFAULT_TILES})",
    )
    parser.add_argument(
        "--cols", type=int, default=DEFAULT_COLS,
        help=f"Column count in the tile grid (default: {DEFAULT_COLS})",
    )
    add_common_arguments(parser)
    args = parser.parse_args()

    samples, label = prepare_from_args(args)
    sample_times_local = _sample_times(0.0, args.duration, args.tiles)

    for cls in effects_from_args(args):
        # Fresh pipeline per effect: several effects carry module-level
        # state that only resets on __init__.  Cheap at 60s of audio.
        frames = run_pipeline(samples)
        if not frames:
            print("  ! No frames generated (window too short?)")
            continue
        effect = cls()
        try:
            out = run_for_effect(
                effect, frames, sample_times_local, label, args.out_dir, args.cols,
            )
            print(f"  {cls.name:<22} → {out}")
        except Exception as exc:
            print(f"  {cls.name:<22} ! failed: {exc}")


if __name__ == "__main__":
    main()
