"""Offline visualization diagnostics for music-reactive effects.

Three plot modules share a common audio-loading and metric-collection
pipeline:

- ``contact_sheet`` — grid of snapshots rendered with real Air75 V2 key
  geometry. Best for 2D / structural effects (Polarity, Mycelium,
  Navier-Stokes) where frame shape matters more than time dynamics.
- ``kymograph`` — space-time heatmaps of individual keyboard rows. Best
  for 1D-ish effects (waves, scrolls, feedback trails) where you want to
  see velocity and decay as diagonal structure.
- ``timeseries`` — 4-panel audio input + brightness + spatial variance +
  frame delta. Best for auditing an effect's *response* rather than its
  appearance.

Each module has its own CLI and is runnable via ``python -m``::

    uv run python -m nuphy_rgb.diagnostics.contact_sheet --all
    uv run python -m nuphy_rgb.diagnostics.kymograph "Polarity"
    uv run python -m nuphy_rgb.diagnostics.timeseries "Aurora"

Shared infrastructure (effect resolution, audio pipeline, metric
collection) lives in ``_common``.
"""
