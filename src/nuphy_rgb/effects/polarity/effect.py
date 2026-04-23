"""Polarity: 12 charged bodies on a torus, one per pitch class.

Each of the 12 bodies is permanently assigned one pitch class k in 0..11 with
a hardcoded charge ``cos(2 * pi * k / 12)``.  The body's **mass** and
**brightness** are modulated by ``chroma[k]`` from the live audio frame:
silent pitches weigh nothing and emit nothing, but they are still there,
drifting under the forces imposed by the currently-active pitches.  Beats
deliver velocity impulses scaled by chroma weight, so the playing notes get
kicked and the silent ones stay passive.

Why this exists: Interval Field v1 spawned ephemeral particles on beats.
With a typical beat rate that gave you 1-2 particles on the grid at any
moment — not enough for a pairwise-force simulation to visibly do anything.
Polarity inherits the load-bearing invariant of v1 (``charge = cos(2 * pi *
k / 12)`` so interval = force product) but borrows Three Body's architecture:
a fixed set of persistent bodies and a decaying trail buffer, so the physics
is always observable.

Consequences of the mapping:
  * Tritone pair (C + F#, charges +1 and -1) attract maximally — the most
    dissonant interval physically slams its bodies together.
  * Octaves collapse onto the same pitch class, so the drum lock-in problem
    doesn't even exist here: kick drums concentrate mass + impulses on a
    single body, which flies around chaotically while the others coast.
  * Sustained chords light up 3 bodies whose charges interact via the
    consonance table — major chords form stable triangular constellations,
    diminished chords (containing a tritone) are unstable and fling apart.

See research/interval_field.md for the original design doc; the charge rule
is identical but the architecture is different.
"""

from __future__ import annotations

import colorsys
import math

import numpy as np

from nuphy_rgb.plugin_api import (
    AudioFrame,
    MAX_COLS,
    NUM_CHROMA_BINS,
    NUM_ROWS,
    VisualizerParam,
    grid_to_leds,
)

_DEFAULT_DT = 1.0 / 30.0
_MAX_DT = 0.1
_SUBSTEPS = 6
_W = float(MAX_COLS)  # 16
_H = float(NUM_ROWS)  # 6
_N = NUM_CHROMA_BINS  # 12

# Fixed charge per pitch class.  Hardcoded, not tunable — this formula is
# the whole point of the effect.  k=0 (C) and k=6 (F#) form the maximum
# dissonance pair (charge product = -1, maximum attraction).
_CHARGES: np.ndarray = np.cos(2.0 * np.pi * np.arange(_N) / _N)
# Hue per body: matches the pitch class / 12 convention used throughout
# the project.  C is red, F# is cyan, etc.
_HUES: np.ndarray = np.arange(_N) / _N
# Cached per-body RGB tuples so we don't re-run hsv_to_rgb per frame.
_BODY_RGB: np.ndarray = np.array(
    [colorsys.hsv_to_rgb(float(h), 0.9, 1.0) for h in _HUES],
    dtype=np.float64,
)


def _wrap(value: np.ndarray, size: float) -> np.ndarray:
    return value - np.floor(value / size) * size


def _min_image_vec(delta: np.ndarray, size: float) -> np.ndarray:
    """Vectorized shortest displacement on a periodic domain."""
    return delta - size * np.round(delta / size)


def _initial_ring() -> np.ndarray:
    """Spread 12 bodies around an ellipse in the grid center.

    Using the circle-of-semitones as the initial geometric arrangement:
    pitch class k sits at angle ``2 * pi * k / 12``, and the ellipse is
    sized to comfortably fit inside the 6x16 grid with some margin.  The
    physics immediately deforms this ring based on the charge distribution
    (tritone pairs across the ring attract maximally), so the visual
    starts moving as soon as audio arrives.
    """
    cx = _W / 2.0
    cy = _H / 2.0
    rx = 5.5  # horizontal radius (just under _W/2 so bodies stay in grid)
    ry = 2.0  # vertical radius (bodies confined near mid rows)
    pos = np.zeros((_N, 2), dtype=np.float64)
    for k in range(_N):
        theta = 2.0 * math.pi * k / _N - math.pi / 2.0  # start from top
        pos[k, 0] = cx + rx * math.cos(theta)
        pos[k, 1] = cy + ry * math.sin(theta)
    return pos


class Polarity:
    name = "Polarity"

    def __init__(self) -> None:
        self._pos = _initial_ring()
        self._vel = np.zeros((_N, 2), dtype=np.float64)
        self._acc = np.zeros((_N, 2), dtype=np.float64)
        self._trails = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        self._last_timestamp: float | None = None
        # Deterministic RNG so identical frame sequences produce identical
        # outputs (test_determinism).  Beat impulses are the only
        # non-deterministic inputs and they come from this stream.
        self._rng = np.random.default_rng(0xC0FFEE)

        self.params: dict[str, VisualizerParam] = {
            "force_constant": VisualizerParam(
                value=4.0, default=4.0, min=0.0, max=20.0,
                description="Coulomb force scale K.  Governs how hard bodies push/pull each other.  0 disables interaction entirely.",
            ),
            "softening": VisualizerParam(
                value=0.8, default=0.8, min=0.3, max=2.0,
                description="Plummer softening radius in grid cells.  Prevents r=0 singularities when bodies overlap.",
            ),
            "base_mass": VisualizerParam(
                value=0.1, default=0.1, min=0.0, max=1.0,
                description="Minimum body mass.  At 0, silent pitches feel no force and drift inertially.  Small positive value keeps them gently coupled.",
            ),
            "chroma_mass_gain": VisualizerParam(
                value=1.6, default=1.6, min=0.0, max=4.0,
                description="How much chroma weight contributes to a body's mass.  Active pitches become heavier and pull harder.",
            ),
            "beat_kick": VisualizerParam(
                value=6.0, default=6.0, min=0.0, max=20.0,
                description="Velocity impulse magnitude on beat, scaled per body by its chroma weight.  Only currently-playing notes get kicked.",
            ),
            "max_speed": VisualizerParam(
                value=18.0, default=18.0, min=5.0, max=40.0,
                description="Per-body speed ceiling in grid cells per second.  Prevents runaway from resonant kicks.",
            ),
            "silence_drag": VisualizerParam(
                value=0.02, default=0.02, min=0.0, max=0.2,
                description="Velocity drag applied only during silence.  Lets the system coast during music and slowly come to rest when audio stops.",
            ),
            "decay_low": VisualizerParam(
                value=0.80, default=0.80, min=0.60, max=0.95,
                description="Trail decay at silence (lower = shorter tails, faster fade to black).",
            ),
            "decay_high": VisualizerParam(
                value=0.96, default=0.96, min=0.90, max=0.99,
                description="Trail decay at full volume (higher = longer tails, more motion smearing).",
            ),
            "body_brightness": VisualizerParam(
                value=1.3, default=1.3, min=0.3, max=3.0,
                description="Deposit intensity per body per frame.  Raised for brighter overall output.",
            ),
            "brightness_scale": VisualizerParam(
                value=1.5, default=1.5, min=0.5, max=3.0,
                description="Output brightness multiplier applied after trail compositing.",
            ),
            "chroma_threshold": VisualizerParam(
                value=0.05, default=0.05, min=0.0, max=0.5,
                description="Bodies with chroma weight below this are not rendered this frame.  Prevents background noise from painting all 12 pitch classes faintly.",
            ),
        }

    # ------------------------------------------------------------------
    # Main render loop
    # ------------------------------------------------------------------

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._compute_dt(frame.timestamp)
        chroma = np.asarray(frame.chroma, dtype=np.float64)
        masses = self._compute_masses(chroma)

        self._apply_beat_kicks(frame, chroma)

        sub_dt = dt / _SUBSTEPS
        for _ in range(_SUBSTEPS):
            self._verlet_step(sub_dt, masses)

        self._apply_silence_drag(dt, frame.raw_rms)
        self._clamp_speed()

        decay = self._compute_decay(frame.raw_rms)
        self._trails *= decay
        self._deposit(chroma)
        np.clip(self._trails, 0.0, 1.0, out=self._trails)

        scale = self.params["brightness_scale"].get()
        output = np.clip(self._trails * scale, 0.0, 1.0)
        return grid_to_leds(output)

    # ------------------------------------------------------------------
    # Time
    # ------------------------------------------------------------------

    def _compute_dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            dt = _DEFAULT_DT
        else:
            dt = max(timestamp - self._last_timestamp, 1e-4)
        self._last_timestamp = timestamp
        return min(dt, _MAX_DT)

    # ------------------------------------------------------------------
    # Physics
    # ------------------------------------------------------------------

    def _compute_masses(self, chroma: np.ndarray) -> np.ndarray:
        base = self.params["base_mass"].get()
        gain = self.params["chroma_mass_gain"].get()
        return base + gain * np.maximum(chroma, 0.0)

    def _compute_accel(
        self, pos: np.ndarray, masses: np.ndarray,
    ) -> np.ndarray:
        """Pairwise Coulomb forces with toroidal minimum-image convention.

        Sign convention: positive charge product (like charges) must push
        body i *away* from body j.  The formula used is

            f_i = -K * q_i * q_j * (r_j - r_i) / |r|^3

        The leading minus sign ensures like charges repel and opposite
        charges attract.  Verified by the unit tests.
        """
        K = self.params["force_constant"].get()
        eps2 = self.params["softening"].get() ** 2
        acc = np.zeros_like(pos)
        if K == 0.0:
            return acc
        for i in range(_N):
            dx = _min_image_vec(pos[:, 0] - pos[i, 0], _W)
            dy = _min_image_vec(pos[:, 1] - pos[i, 1], _H)
            r2 = dx * dx + dy * dy + eps2
            inv_r3 = r2 ** -1.5
            inv_r3[i] = 0.0
            qq = _CHARGES[i] * _CHARGES
            factor = -K * qq * masses * inv_r3
            acc[i, 0] = np.sum(factor * dx) / max(masses[i], 1e-6)
            acc[i, 1] = np.sum(factor * dy) / max(masses[i], 1e-6)
        return acc

    def _verlet_step(self, dt: float, masses: np.ndarray) -> None:
        self._vel += 0.5 * self._acc * dt
        self._pos[:, 0] = _wrap(self._pos[:, 0] + self._vel[:, 0] * dt, _W)
        self._pos[:, 1] = _wrap(self._pos[:, 1] + self._vel[:, 1] * dt, _H)
        self._acc = self._compute_accel(self._pos, masses)
        self._vel += 0.5 * self._acc * dt

    def _apply_beat_kicks(
        self, frame: AudioFrame, chroma: np.ndarray,
    ) -> None:
        """Distribute velocity impulses across bodies proportional to chroma.

        On beat, every body that's currently playing gets a random-direction
        velocity kick scaled by its chroma weight.  Silent bodies receive
        no impulse, so the kicks go to the notes the music is actually
        playing.  This is what keeps the simulation coupled to melodic
        content rather than just reacting to the beat track.
        """
        if not (frame.is_beat or frame.mid_beat or frame.high_beat):
            return
        kick = self.params["beat_kick"].get()
        if kick <= 0.0:
            return
        # Any beat flag triggers kicks; scale total impulse by how many
        # bands fired so that full-spectrum hits are more energetic.
        band_count = int(frame.is_beat) + int(frame.mid_beat) + int(frame.high_beat)
        strength = kick * band_count
        for k in range(_N):
            weight = float(chroma[k])
            if weight <= 0.0:
                continue
            angle = self._rng.uniform(0.0, 2.0 * math.pi)
            self._vel[k, 0] += strength * weight * math.cos(angle)
            self._vel[k, 1] += strength * weight * math.sin(angle)

    def _apply_silence_drag(self, dt: float, raw_rms: float) -> None:
        silence = 1.0 - min(max(raw_rms * 3.0, 0.0), 1.0)
        drag = self.params["silence_drag"].get() * silence
        self._vel *= max(0.0, 1.0 - drag * dt * 30.0)

    def _clamp_speed(self) -> None:
        max_speed = self.params["max_speed"].get()
        speeds = np.linalg.norm(self._vel, axis=1)
        over = speeds > max_speed
        if np.any(over):
            self._vel[over] *= (max_speed / speeds[over])[:, None]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _compute_decay(self, raw_rms: float) -> float:
        loud = min(max(raw_rms * 3.0, 0.0), 1.0)
        low = self.params["decay_low"].get()
        high = self.params["decay_high"].get()
        return low + (high - low) * loud

    def _deposit(self, chroma: np.ndarray) -> None:
        intensity = self.params["body_brightness"].get()
        threshold = self.params["chroma_threshold"].get()
        for k in range(_N):
            weight = float(chroma[k])
            if weight < threshold:
                continue
            x = float(self._pos[k, 0])
            y = float(self._pos[k, 1])
            r, g, b = _BODY_RGB[k]
            value = intensity * weight
            self._splat(x, y, r * value, g * value, b * value)

    def _splat(
        self,
        x: float,
        y: float,
        r: float,
        g: float,
        b: float,
    ) -> None:
        """Bilinear deposit with torus wrap in both axes."""
        c0 = int(math.floor(x)) % MAX_COLS
        row0 = int(math.floor(y)) % NUM_ROWS
        c1 = (c0 + 1) % MAX_COLS
        row1 = (row0 + 1) % NUM_ROWS
        fx = x - math.floor(x)
        fy = y - math.floor(y)
        t = self._trails
        w00 = (1.0 - fx) * (1.0 - fy)
        w01 = fx * (1.0 - fy)
        w10 = (1.0 - fx) * fy
        w11 = fx * fy
        t[row0, c0, 0] += w00 * r
        t[row0, c0, 1] += w00 * g
        t[row0, c0, 2] += w00 * b
        t[row0, c1, 0] += w01 * r
        t[row0, c1, 1] += w01 * g
        t[row0, c1, 2] += w01 * b
        t[row1, c0, 0] += w10 * r
        t[row1, c0, 1] += w10 * g
        t[row1, c0, 2] += w10 * b
        t[row1, c1, 0] += w11 * r
        t[row1, c1, 1] += w11 * g
        t[row1, c1, 2] += w11 * b
