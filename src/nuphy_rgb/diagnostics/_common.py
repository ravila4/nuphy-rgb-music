"""Shared infrastructure for diagnostics plot modules.

- Effect resolution (built-ins + plugins in ~/.config/nuphy-rgb/effects/)
- Real-audio pipeline: librosa → AudioCapture external queue → AudioFrames
- Per-frame metric collection for kymographs and time series
- Contact sheet helper: render an effect only at specified sample times

Defaults target the staple benchmark track — Bowie, Space Oddity 2015
Remaster, first 60 seconds — but all CLIs accept --song/--start/--duration
overrides.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import queue
import sys
from pathlib import Path

import librosa
import numpy as np

from nuphy_rgb.audio import AudioCapture, AudioFrame, BLOCK_SIZE, SAMPLE_RATE
from nuphy_rgb.effects import ALL_EFFECTS
from nuphy_rgb.effects.grid import LED_ROW_COL, MAX_COLS, NUM_LEDS, NUM_ROWS


# ---------------------------------------------------------------------------
# Staple benchmark
# ---------------------------------------------------------------------------

STAPLE_SONG: Path | None = None
_staple_candidate = (
    Path.home()
    / "Library/CloudStorage/Dropbox/Music/deemix/David Bowie"
    / "David Bowie (aka Space Oddity) (2015 Remaster)"
    / " 01 Space Oddity (2015 Remaster).mp3"
)
if _staple_candidate.exists():
    STAPLE_SONG = _staple_candidate
STAPLE_START = 0.0
STAPLE_DURATION = 60.0

# Default output directory. Gitignored; diagnostics aren't committed.
DEFAULT_OUT_DIR = Path(".scratch")

_PLUGIN_DIR = Path.home() / ".config/nuphy-rgb/effects"


# ---------------------------------------------------------------------------
# Effect resolution
# ---------------------------------------------------------------------------


def _discover_plugin_classes() -> list[type]:
    found: list[type] = []
    if not _PLUGIN_DIR.exists():
        return found
    for path in sorted(_PLUGIN_DIR.rglob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            # Register before exec so @dataclass inside the plugin can
            # resolve cls.__module__ via sys.modules (Python 3.13).
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)
        except Exception as exc:
            print(f"Warning: failed to load plugin {path.name}: {exc}")
            continue
        for attr in vars(mod).values():
            if (
                isinstance(attr, type)
                and getattr(attr, "__module__", None) == module_name
                and isinstance(getattr(attr, "name", None), str)
                and callable(getattr(attr, "render", None))
            ):
                found.append(attr)
    return found


def all_effect_classes() -> list[type]:
    """Every effect we can diagnose — built-ins followed by plugins."""
    return list(ALL_EFFECTS) + _discover_plugin_classes()


def resolve_effect(name: str) -> object:
    """Find a built-in or plugin effect by name (case-insensitive)."""
    name_lower = name.lower()
    candidates = all_effect_classes()
    for cls in candidates:
        if cls.name.lower() == name_lower:
            return cls()
    for cls in candidates:
        if name_lower in cls.name.lower():
            return cls()
    available = ", ".join(f'"{cls.name}"' for cls in candidates)
    print(f"Unknown effect: {name!r}")
    print(f"Available: {available}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Audio loading and pipeline
# ---------------------------------------------------------------------------


def load_audio(path: Path, start: float, duration: float) -> np.ndarray:
    """Load *duration* seconds starting at *start* as mono float32 @ SAMPLE_RATE."""
    samples, _ = librosa.load(
        str(path), sr=SAMPLE_RATE, mono=True, offset=start, duration=duration
    )
    return samples.astype(np.float32)


def run_pipeline(samples: np.ndarray) -> list[AudioFrame]:
    """Feed a sample array through AudioCapture and return AudioFrames.

    Each frame's timestamp is rewritten to audio-position time (not
    monotonic) so effects with time-driven oscillations advance correctly
    in this tight offline loop.
    """
    q: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
    capture = AudioCapture(external_queue=q)
    capture.start()

    frames: list[AudioFrame] = []
    hop = BLOCK_SIZE
    dt = hop / SAMPLE_RATE
    n_chunks = len(samples) // hop

    for i in range(n_chunks):
        chunk = samples[i * hop : (i + 1) * hop]
        q.put_nowait(chunk)
        frame = capture.process_latest()
        if frame is None:
            continue
        frame = dataclasses.replace(frame, timestamp=i * dt)
        frames.append(frame)

    capture.stop()
    return frames


# ---------------------------------------------------------------------------
# Effect evaluation
# ---------------------------------------------------------------------------


def leds_to_grid(leds: list[tuple[int, int, int]]) -> np.ndarray:
    """Convert 84 RGB tuples to a (NUM_ROWS, MAX_COLS, 3) uint8 array."""
    grid = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.uint8)
    for idx in range(NUM_LEDS):
        r, c = LED_ROW_COL[idx]
        grid[r, c] = leds[idx]
    return grid


def collect_metrics(
    effect: object, frames: list[AudioFrame]
) -> dict[str, np.ndarray]:
    """Run *effect* on every frame, return grids + per-frame metrics.

    Metrics dict keys:
        grids            — (N, NUM_ROWS, MAX_COLS, 3) uint8
        times            — (N,) float, audio-position seconds
        bass, mids, highs — (N,) float, per-band energy
        beats            — (N,) bool
        mean_brightness  — (N,) float, per-frame 0..1
        spatial_variance — (N,) float, per-frame 0..1
        frame_delta      — (N,) float, per-frame 0..1
        chroma_argmax    — (N,) int, -1 if chroma is zero
        chroma_peak      — (N,) float
    """
    n = len(frames)
    grids = np.zeros((n, NUM_ROWS, MAX_COLS, 3), dtype=np.uint8)
    times = np.zeros(n)
    bass_vals = np.zeros(n)
    mids_vals = np.zeros(n)
    highs_vals = np.zeros(n)
    beat_flags = np.zeros(n, dtype=bool)
    mean_brightness = np.zeros(n)
    spatial_variance = np.zeros(n)
    frame_delta = np.zeros(n)
    chroma_argmax = np.zeros(n, dtype=np.int64)
    chroma_peak = np.zeros(n)

    prev_brightness: np.ndarray | None = None

    for i, frame in enumerate(frames):
        leds = effect.render(frame)  # type: ignore[union-attr]
        if len(leds) != NUM_LEDS:
            raise ValueError(
                f"{type(effect).__name__}.render() returned {len(leds)} LEDs, "
                f"expected {NUM_LEDS}",
            )
        grids[i] = leds_to_grid(leds)
        times[i] = frame.timestamp
        bass_vals[i] = frame.bass
        mids_vals[i] = frame.mids
        highs_vals[i] = frame.highs
        beat_flags[i] = frame.is_beat
        chroma = np.asarray(frame.chroma, dtype=np.float64)
        chroma_argmax[i] = int(np.argmax(chroma)) if chroma.sum() > 0 else -1
        chroma_peak[i] = float(chroma.max())

        brightness = np.array(
            [(r + g + b) / (3.0 * 255.0) for r, g, b in leds]
        )
        mean_brightness[i] = float(np.mean(brightness))
        spatial_variance[i] = float(np.std(brightness))
        if prev_brightness is not None:
            frame_delta[i] = float(np.mean(np.abs(brightness - prev_brightness)))
        prev_brightness = brightness

    return {
        "grids": grids,
        "times": times,
        "bass": bass_vals,
        "mids": mids_vals,
        "highs": highs_vals,
        "beats": beat_flags,
        "mean_brightness": mean_brightness,
        "spatial_variance": spatial_variance,
        "frame_delta": frame_delta,
        "chroma_argmax": chroma_argmax,
        "chroma_peak": chroma_peak,
    }


def render_effect_at_samples(
    effect: object,
    frames: list[AudioFrame],
    sample_times: list[float],
) -> tuple[list[np.ndarray], list[float]]:
    """Render *effect* on every frame, keep LEDs at the nearest frames to each
    *sample_times* entry.

    The effect must see every frame (state is stateful) but we only keep
    84-LED arrays at the sample indices. Returns (snapshots, displayed_times)
    where displayed_times is the actual audio-position time of the nearest
    frame for each requested sample.
    """
    if not frames:
        return [], []
    timestamps = np.array([f.timestamp for f in frames])
    sample_indices = [int(np.argmin(np.abs(timestamps - t))) for t in sample_times]
    wanted = set(sample_indices)

    kept: dict[int, np.ndarray] = {}
    for i, frame in enumerate(frames):
        leds = effect.render(frame)  # type: ignore[union-attr]
        if i in wanted:
            kept[i] = np.asarray(leds, dtype=np.uint8)

    return (
        [kept[i] for i in sample_indices],
        [float(timestamps[i]) for i in sample_indices],
    )


# ---------------------------------------------------------------------------
# Shared CLI arg pattern
# ---------------------------------------------------------------------------


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach the --song / --start / --duration / --out-dir flags used by
    every diagnostic CLI."""
    required = STAPLE_SONG is None
    parser.add_argument(
        "--song", type=Path, default=STAPLE_SONG,
        required=required,
        help="Audio file" + ("" if required else " (default: Space Oddity staple)"),
    )
    parser.add_argument(
        "--start", type=float, default=STAPLE_START,
        help=f"Start offset in seconds (default: {STAPLE_START})",
    )
    parser.add_argument(
        "--duration", type=float, default=STAPLE_DURATION,
        help=f"Window duration in seconds (default: {STAPLE_DURATION})",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUT_DIR})",
    )


def song_label(song: Path, start: float, duration: float) -> str:
    return f"{song.stem[:48]} ({start:.0f}s–{start + duration:.0f}s)"


def prepare_from_args(args: argparse.Namespace) -> tuple[np.ndarray, str]:
    """Validate --song, mkdir --out-dir, load audio, build the label.

    Returns ``(samples, label)``.  Each CLI then calls ``run_pipeline(samples)``
    itself — fresh pipeline per effect is important because several effects
    share module-level state that only resets on ``__init__``.

    Side effect: creates ``args.out_dir`` if missing.
    """
    if not args.song.exists():
        print(f"Audio file not found: {args.song}")
        sys.exit(1)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Loading {args.song.name} [{args.start:.0f}s, +{args.duration:.0f}s]...")
    samples = load_audio(args.song, args.start, args.duration)
    print(f"Loaded {len(samples) / SAMPLE_RATE:.1f}s at {SAMPLE_RATE} Hz")
    return samples, song_label(args.song, args.start, args.duration)


def effects_from_args(args: argparse.Namespace) -> list[type]:
    """Resolve which effects to run based on the CLI args.

    If ``args.all`` is set or ``args.effect`` is missing, return every
    available effect class. Otherwise resolve the single named effect.
    """
    if getattr(args, "all", False) or getattr(args, "effect", None) is None:
        classes = all_effect_classes()
        print(f"Rendering {len(classes)} effects...")
        return classes
    return [type(resolve_effect(args.effect))]
