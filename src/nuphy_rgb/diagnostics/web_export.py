"""Export an effect as a web-playable asset bundle.

The contact sheet and kymograph diagnostics render static images. This
module produces the ingredients for an *interactive* keyboard: a static
SVG of the Air75 V2 layout with stable LED ids, a packed binary dump of
per-frame RGB values, a tiny JSON manifest, and an MP3 of the audio clip
that drove the effect. A small JS player (lives in the blog repo) loads
all four and drives ``<rect fill>`` updates off ``audio.currentTime`` via
``requestAnimationFrame``.

Designed for the ravila.dev blog post so readers can play, pause, and
scrub a real effect synced to the track that produced it — not just
watch a video.

Usage::

    uv run python -m nuphy_rgb.diagnostics.web_export "Interference Pond" \\
        --duration 30 --out-dir ~/Projects/ravila.dev/posts/.../player
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.diagnostics._common import (
    add_common_arguments,
    effects_from_args,
    prepare_from_args,
    run_pipeline,
)
from nuphy_rgb.diagnostics.geometry import BOARD_H_U, BOARD_W_U, KEY_RECTS

SVG_PAD = 0.06
SVG_RADIUS = 0.12


def build_keyboard_svg(background: str = "#111111") -> str:
    """Return a static SVG of the 84-key board, one ``<rect id="led-N">`` per LED.

    All rects start black; the JS player paints fills at runtime. The
    viewBox is in keyboard units so the SVG scales to any container
    width without touching stroke thicknesses.
    """
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {BOARD_W_U} {BOARD_H_U}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'class="nuphy-keyboard">',
        f'<rect x="0" y="0" width="{BOARD_W_U}" height="{BOARD_H_U}" '
        f'fill="{background}"/>',
        '<g stroke="#404040" stroke-width="0.015">',
    ]
    for rect in KEY_RECTS:
        x = rect.x_u + SVG_PAD / 2
        y = rect.y_u + SVG_PAD / 2
        w = rect.w_u - SVG_PAD
        h = rect.h_u - SVG_PAD
        parts.append(
            f'<rect id="led-{rect.led}" '
            f'x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}" '
            f'rx="{SVG_RADIUS}" ry="{SVG_RADIUS}" fill="#000000"/>'
        )
    parts.append('</g></svg>')
    return '\n'.join(parts)


def render_frames_array(
    effect: object, frames: list[AudioFrame]
) -> np.ndarray:
    """Run *effect* over every frame, stack LED snapshots into (N, 84, 3) uint8."""
    if not frames:
        return np.zeros((0, 84, 3), dtype=np.uint8)
    out = np.zeros((len(frames), 84, 3), dtype=np.uint8)
    for i, frame in enumerate(frames):
        leds = effect.render(frame)  # type: ignore[union-attr]
        out[i] = np.asarray(leds, dtype=np.uint8)
    return out


def _slice_audio_mp3(
    song: Path, start: float, duration: float, out: Path
) -> None:
    """Use ffmpeg to slice *song* into a variable-bitrate MP3 at *out*.

    Re-encodes (not stream-copy) because stream-copy gives sample-accurate
    cuts only on keyframes. A 30s VBR MP3 at q=4 is ~500 KB — fine for a
    blog post, and the re-encode keeps audio in sync with the frame dump.
    """
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{start}",
        "-t", f"{duration}",
        "-i", str(song),
        "-codec:a", "libmp3lame", "-q:a", "4",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def write_web_export(
    effect: object,
    frames: list[AudioFrame],
    song: Path,
    start: float,
    duration: float,
    label: str,
    out_dir: Path,
) -> dict[str, Path]:
    """Write keyboard.svg, frames.bin, meta.json, audio.mp3 to *out_dir*.

    Returns the four paths keyed by role.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    svg_path = out_dir / "keyboard.svg"
    svg_path.write_text(build_keyboard_svg(), encoding="utf-8")

    array = render_frames_array(effect, frames)
    bin_path = out_dir / "frames.bin"
    bin_path.write_bytes(array.tobytes(order="C"))

    # Use the first and last frame timestamps for an accurate fps — the
    # pipeline's nominal rate (BLOCK_SIZE/SAMPLE_RATE ≈ 46.9 Hz) is a
    # good-enough fallback when there's only one frame.
    if len(frames) >= 2:
        dt = (frames[-1].timestamp - frames[0].timestamp) / (len(frames) - 1)
        fps = 1.0 / dt if dt > 0 else 0.0
    else:
        fps = 0.0

    meta_path = out_dir / "meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "effect": getattr(effect, "name", type(effect).__name__),
                "label": label,
                "n_frames": int(array.shape[0]),
                "n_leds": int(array.shape[1]),
                "fps": round(fps, 3),
                "duration_s": round(duration, 3),
                "start_s": round(start, 3),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    audio_path = out_dir / "audio.mp3"
    _slice_audio_mp3(song, start, duration, audio_path)

    return {
        "svg": svg_path,
        "frames": bin_path,
        "meta": meta_path,
        "audio": audio_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export an effect as a web-playable SVG+binary bundle",
    )
    parser.add_argument(
        "effect", nargs="?", default=None,
        help="Effect name (default: Interference Pond)",
    )
    add_common_arguments(parser)
    args = parser.parse_args()

    if args.effect is None:
        args.effect = "Interference Pond"

    samples, label = prepare_from_args(args)
    classes = effects_from_args(args)
    if len(classes) != 1:
        print("web_export handles one effect at a time; pass an effect name")
        sys.exit(1)

    frames = run_pipeline(samples)
    if not frames:
        print("No frames produced — window too short?")
        sys.exit(1)

    effect = classes[0]()
    paths = write_web_export(
        effect, frames, args.song, args.start, args.duration, label, args.out_dir,
    )
    for role, path in paths.items():
        size = path.stat().st_size
        print(f"  {role:<7} → {path}  ({size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
