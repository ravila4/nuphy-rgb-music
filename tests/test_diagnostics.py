"""End-to-end smoke tests for the diagnostics plot modules.

Each test feeds a 3-second synthetic sine sweep through run_pipeline,
collects metrics, calls the plot function, and asserts the output PNG
exists and is non-empty. This guards against bitrot — a surprising amount
of the code is import wiring and signature agreement between modules.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nuphy_rgb.audio import SAMPLE_RATE
from nuphy_rgb.diagnostics import _common, contact_sheet, kymograph, timeseries
from nuphy_rgb.effects import InterferencePond


@pytest.fixture
def synthetic_samples() -> np.ndarray:
    """3 seconds of swept sine: quiet → loud, 200 Hz → 2000 Hz.

    Short enough to run fast, long enough that the audio pipeline
    produces a few AudioFrames with non-trivial bass/mid/high content.
    """
    duration = 3.0
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False, dtype=np.float32)
    freq = np.linspace(200.0, 2000.0, n, dtype=np.float32)
    envelope = np.linspace(0.1, 0.8, n, dtype=np.float32)
    return (envelope * np.sin(2 * np.pi * freq * t)).astype(np.float32)


@pytest.fixture
def frames(synthetic_samples: np.ndarray):
    result = _common.run_pipeline(synthetic_samples)
    assert len(result) > 0, "pipeline produced no frames"
    return result


def test_geometry_imports_cleanly():
    from nuphy_rgb.diagnostics.geometry import BOARD_H_U, BOARD_W_U, KEY_RECTS
    assert BOARD_W_U == 16.0
    assert BOARD_H_U == 6.0
    assert len(KEY_RECTS) == 84


def test_resolve_effect_finds_builtin():
    effect = _common.resolve_effect("Interference Pond")
    assert type(effect).__name__ == "InterferencePond"


def test_collect_metrics_shape_and_response(frames):
    metrics = _common.collect_metrics(InterferencePond(), frames)
    n = len(frames)
    assert metrics["grids"].shape == (n, 6, 16, 3)
    assert metrics["times"].shape == (n,)
    assert metrics["chroma_argmax"].shape == (n,)
    # Pipeline is actually wired: non-silent input must produce non-zero
    # brightness at some point. Catches the "pipeline runs but returns
    # zeros" class of bug that a pure shape check misses.
    assert metrics["mean_brightness"].max() > 0.0


def test_contact_sheet_renders(frames, tmp_path: Path):
    sample_times = contact_sheet._sample_times(0.0, 3.0, n_tiles=6)
    out = contact_sheet.run_for_effect(
        InterferencePond(), frames, sample_times,
        label="synthetic sweep",
        out_dir=tmp_path,
        cols=3,
    )
    assert out.exists()
    assert out.stat().st_size > 1000


def test_kymograph_renders(frames, tmp_path: Path):
    out = kymograph.run_for_effect(
        InterferencePond(), frames,
        label="synthetic sweep",
        out_dir=tmp_path,
    )
    assert out.exists()
    assert out.stat().st_size > 1000


def test_timeseries_renders(frames, tmp_path: Path):
    out = timeseries.run_for_effect(
        InterferencePond(), frames,
        label="synthetic sweep",
        out_dir=tmp_path,
    )
    assert out.exists()
    assert out.stat().st_size > 1000
