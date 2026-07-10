"""Excitable Media: a Greenberg-Hastings cellular automaton lit by the music.

The keyboard is a thin dish of excitable tissue -- a Belousov-Zhabotinsky
reaction, a slab of heart muscle, a forest primed to burn. Each key is a cell
in one of three phases: resting (stable, dark), excited (the bright wavefront),
or refractory (the colored wake that cannot re-fire until it relaxes back to
rest). A resting cell ignites when enough von-Neumann neighbors are excited, so
excitation spreads as traveling diamond-shaped wavefronts that curl around each
other and self-annihilate where they collide.

Sound is the energy that keeps the tissue excited; silence is the medium
relaxing to rest. Loudness drives a brightness envelope, onsets spontaneously
ignite fresh cells (new wave sources), each beat spawns a broken wavefront whose
free end curls toward a spiral, and pitch tints the whole medium's hue. With no
stimulation the waves finish their sweep and age around to rest within one
refractory period, so the board decays to black on its own -- the physics is the
silence envelope.

See research/excitable_media.md for the design doc, grounded in Ilachinski,
*Cellular Automata: A Discrete Universe* Section 8 (the Greenberg-Hastings model).
"""

from __future__ import annotations

import colorsys

import numpy as np

from nuphy_rgb.plugin_api import (
    MAX_COLS,
    NUM_ROWS,
    VALID_MASK,
    AudioFrame,
    VisualizerParam,
    freq_to_hue,
    grid_to_leds,
)

_DEFAULT_DT = 1.0 / 30.0
_MAX_DT = 0.1
_MAX_TICKS = 4  # cap CA steps per frame so a lag spike can't run away

# Cell phases are integers: 0 = resting, 1..E = excited, E+1..N-1 = refractory.
_N_EXCITED = 1  # thin one-cell crest

# Render mapping (shared with the tests).
_V_CREST = 1.0    # brightness of the excited leading edge
_V_WAKE = 0.6     # brightness of the freshest refractory cell (fades toward rest)
_SAT_EXCITED = 0.25  # near-white crest (color reads in the wake)
_SAT_WAKE = 0.95     # saturated colored wake
# Each wave is dyed at birth by the music (chroma pitch class -> hue), and that
# color travels with the wavefront, so colliding waves paint moving color
# boundaries and the palette shifts as the song's harmony moves. A small phase
# shift across the wake keeps a Belousov-Zhabotinsky crest->wake gradient.
_HUE_WAKE_SPAN = 0.10

# Stimulation constants. A cold (fully-rested) medium is seeded from a sparse
# random scatter -- Ilachinski's random-initial-state bootstrap; once alive, new
# onsets add point sources and beats add broken fronts.
_SEED_ACTIVE = 0.04
_SEED_REFRACTORY = 0.04
_ONSET_GATE = 0.15   # onset_strength rising edge that counts as a fresh event
_FRONT_LEN = 4       # length of a beat-spawned wavefront


def excited_neighbor_count(excited: np.ndarray) -> np.ndarray:
    """Count each cell's von-Neumann (4-cardinal) excited neighbors.

    Bounded, not toroidal: off-grid neighbors contribute nothing.
    """
    e = excited.astype(np.int32)
    count = np.zeros_like(e)
    count[1:, :] += e[:-1, :]   # neighbor above
    count[:-1, :] += e[1:, :]   # neighbor below
    count[:, 1:] += e[:, :-1]   # neighbor to the left
    count[:, :-1] += e[:, 1:]   # neighbor to the right
    return count


def step(
    state: np.ndarray, n_excited: int, n_states: int, threshold: int
) -> np.ndarray:
    """One Greenberg-Hastings tick.

    Every non-resting cell ages one phase around the cycle (excited ->
    refractory -> ... -> rest). A resting cell ignites (-> excited phase 1) iff
    at least *threshold* of its von-Neumann neighbors are currently excited.
    Refractory cells ignore their neighbors, which is what makes waves travel
    and annihilate on collision. Invalid (missing-key) cells stay resting.
    """
    excited = (state >= 1) & (state <= n_excited)
    counts = excited_neighbor_count(excited)

    new = state.copy()
    moving = state > 0
    new[moving] = state[moving] + 1
    new[new >= n_states] = 0

    ignite = (state == 0) & (counts >= threshold) & VALID_MASK
    new[ignite] = 1

    new[~VALID_MASK] = 0
    return new


def state_to_value(state: np.ndarray, n_excited: int, n_states: int) -> np.ndarray:
    """Phase -> brightness. Resting is black, the excited crest is fully bright,
    and the refractory wake ramps linearly down toward rest."""
    refractory = n_states - 1 - n_excited
    value = np.zeros(state.shape, dtype=np.float64)
    excited = (state >= 1) & (state <= n_excited)
    value[excited] = _V_CREST
    wake = state > n_excited
    if refractory > 0:
        k = (state - n_excited).astype(np.float64)  # 1..refractory
        value[wake] = _V_WAKE * (refractory - k[wake] + 1.0) / refractory
    return value


def state_to_sat(state: np.ndarray, n_excited: int) -> np.ndarray:
    """Phase -> saturation. The excited crest is near-white; everything else
    (the colored wake) is saturated."""
    sat = np.full(state.shape, _SAT_WAKE, dtype=np.float64)
    excited = (state >= 1) & (state <= n_excited)
    sat[excited] = _SAT_EXCITED
    return sat


def spawn_front(
    state: np.ndarray,
    r0: int,
    c0: int,
    length: int,
    gap_frac: float,
    n_excited: int,
) -> None:
    """Write a vertical wavefront in column *c0*, in place.

    The first ``gap_frac`` of the segment is set refractory instead of excited,
    capping that end so the wave can only propagate from its free end -- a
    broken front, the seed of a rotating spiral. gap_frac=0 gives a full
    symmetric front (an expanding ring). Cells off-grid or on missing keys are
    skipped.
    """
    if c0 < 0 or c0 >= MAX_COLS:
        return
    n_gap = int(round(gap_frac * length))
    for i in range(length):
        rr = r0 + i
        if rr < 0 or rr >= NUM_ROWS or not VALID_MASK[rr, c0]:
            continue
        state[rr, c0] = (n_excited + 1) if i < n_gap else 1


def seed_noise(
    state: np.ndarray,
    rng: np.random.Generator,
    active_frac: float,
    refractory_frac: float,
    n_excited: int,
    n_states: int,
) -> None:
    """Scatter random excited + refractory cells onto the valid grid, in place.

    This is the random-initial-state bootstrap from which spiral waves
    self-organize (Ilachinski's ~5% active / ~5% refractory seed).
    """
    r = rng.random(state.shape)
    phases = rng.integers(n_excited + 1, max(n_excited + 2, n_states), size=state.shape)
    excite = VALID_MASK & (r < active_frac)
    refr = VALID_MASK & (r >= active_frac) & (r < active_frac + refractory_frac)
    state[excite] = 1
    state[refr] = phases[refr]


class ExcitableMedia:
    name = "Excitable Media"

    def __init__(self) -> None:
        self._rng = np.random.default_rng(0xE7C1)
        self._state = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.int32)
        self._hue = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        self._glow = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        self._bright = 0.0
        self._base_hue = 0.0
        self._prev_onset = 0.0
        self._n_excited = _N_EXCITED
        self._last_timestamp: float | None = None
        self._tick_accum = 0.0

        self.params: dict[str, VisualizerParam] = {
            "tick_hz": VisualizerParam(
                value=12.0, default=12.0, min=4.0, max=30.0,
                description="Cellular-automaton steps per second -- the wave propagation speed.",
            ),
            "refractory": VisualizerParam(
                value=4.0, default=4.0, min=1.0, max=8.0,
                description="Refractory period in ticks (rounded). Sets the wavelength / spacing between wavefronts.",
            ),
            "excite_thresh": VisualizerParam(
                value=1.0, default=1.0, min=1.0, max=3.0,
                description="Excited neighbors needed to ignite a resting cell (rounded). Higher = waves spread harder to sustain.",
            ),
            "feed_rate": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=2.0,
                description="Extra wave sources launched per onset (times onset_strength). Higher = denser, busier field; lower = sparse, legible single waves.",
            ),
            "spiral_gap": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
                description="Fraction of a beat-spawned front pre-set refractory. 0 = symmetric rings; >0 = broken fronts that curl into spirals.",
            ),
            "bass_excite": VisualizerParam(
                value=0.6, default=0.6, min=0.0, max=1.0,
                description="How strongly loud bass lowers the ignition threshold, making the medium more excitable on heavy low end.",
            ),
            "glow": VisualizerParam(
                value=0.6, default=0.6, min=0.0, max=0.95,
                description="Temporal smoothing of the wake: higher leaves a longer motion-blurred trail behind each wave.",
            ),
            "silence_thresh": VisualizerParam(
                value=0.02, default=0.02, min=0.0, max=0.2,
                description="raw_rms below this stops all stimulation, letting the medium relax to black.",
            ),
            "ember_decay": VisualizerParam(
                value=0.9, default=0.9, min=0.7, max=0.99,
                description="Per-frame brightness-envelope release when the music drops.",
            ),
        }

    def _dt(self, timestamp: float) -> float:
        if self._last_timestamp is None:
            self._last_timestamp = timestamp
            return _DEFAULT_DT
        dt = timestamp - self._last_timestamp
        self._last_timestamp = timestamp
        if dt <= 0.0:
            return _DEFAULT_DT
        return min(dt, _MAX_DT)

    def _ignite_random(self, n: int, hue: float) -> None:
        """Ignite up to *n* random resting valid cells as point sources, each
        dyed with *hue* (the color of the music at spawn time)."""
        if n <= 0:
            return
        resting = np.argwhere((self._state == 0) & VALID_MASK)
        if len(resting) == 0:
            return
        n = min(n, len(resting))
        idx = self._rng.choice(len(resting), size=n, replace=False)
        for j in idx:
            r, c = resting[j]
            self._state[r, c] = 1
            self._hue[r, c] = hue

    def _spawn_random_front(self, gap_frac: float, hue: float) -> None:
        c0 = int(self._rng.integers(0, MAX_COLS))
        r0 = int(self._rng.integers(0, max(1, NUM_ROWS - _FRONT_LEN + 1)))
        prev_col = self._state[:, c0].copy()
        spawn_front(self._state, r0, c0, _FRONT_LEN, gap_frac, self._n_excited)
        rows = np.nonzero(self._state[:, c0] != prev_col)[0]
        self._hue[rows, c0] = hue

    def _music_hue(self, frame: AudioFrame) -> float:
        """The color of the current moment: the dominant pitch class (chroma
        argmax) around the hue wheel, falling back to the dominant frequency."""
        chroma = np.asarray(frame.chroma, dtype=np.float64)
        if chroma.sum() > 1e-6:
            return float(np.argmax(chroma)) / 12.0
        if frame.dominant_freq > 0.0:
            return freq_to_hue(frame.dominant_freq)
        return self._base_hue

    def _propagate_hue(self, prev: np.ndarray) -> None:
        """Newly-excited cells inherit their color from the excited neighbors
        that fired them (von-Neumann circular mean), so a wave carries its birth
        color outward as it spreads."""
        newly = (self._state == 1) & (prev == 0)
        if not newly.any():
            return
        w = ((prev >= 1) & (prev <= self._n_excited)).astype(np.float64)
        zc = w * np.exp(2j * np.pi * self._hue)
        acc = np.zeros_like(zc)
        acc[1:, :] += zc[:-1, :]
        acc[:-1, :] += zc[1:, :]
        acc[:, 1:] += zc[:, :-1]
        acc[:, :-1] += zc[:, 1:]
        nb_hue = (np.angle(acc) / (2 * np.pi)) % 1.0
        take = newly & (np.abs(acc) > 1e-9)
        self._hue[take] = nb_hue[take]

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        dt = self._dt(frame.timestamp)
        p = self.params

        # --- brightness envelope: fast attack, slow release -----------------
        target = min(1.0, 1.4 * frame.rms)
        if target > self._bright:
            self._bright = target
        else:
            e = p["ember_decay"].value
            self._bright = e * self._bright + (1.0 - e) * target

        # --- color of the moment (dyes waves born this frame) ---------------
        music_hue = self._music_hue(frame)
        self._base_hue += 0.1 * (music_hue - self._base_hue)

        # --- cellular-automaton propagation (framerate independent) ---------
        refractory = max(1, int(round(p["refractory"].value)))
        n_states = 1 + self._n_excited + refractory
        thr = max(1, int(round(p["excite_thresh"].value - p["bass_excite"].value * frame.bass)))

        self._tick_accum += p["tick_hz"].value * dt
        n_ticks = min(_MAX_TICKS, int(self._tick_accum))
        self._tick_accum -= n_ticks
        for _ in range(n_ticks):
            prev = self._state
            self._state = step(prev, self._n_excited, n_states, thr)
            self._propagate_hue(prev)

        # --- stimulation: musical events launch waves -----------------------
        # Waves come from transient events (onsets, beats), not a constant feed,
        # so the medium keeps dark space between wavefronts instead of
        # saturating. onset_strength is edge-triggered -- one onset, one event.
        onset = frame.onset_strength
        onset_edge = onset > _ONSET_GATE and self._prev_onset <= _ONSET_GATE
        self._prev_onset = onset

        if frame.raw_rms >= p["silence_thresh"].value:
            alive = bool(np.any(self._state != 0))
            if not alive and (onset_edge or frame.is_beat):
                # cold start: a sparse random scatter self-organizes into waves
                prev_state = self._state.copy()
                seed_noise(
                    self._state, self._rng,
                    _SEED_ACTIVE, _SEED_REFRACTORY, self._n_excited, n_states,
                )
                self._hue[self._state != prev_state] = music_hue
            else:
                if onset_edge:
                    self._ignite_random(1 + int(p["feed_rate"].value * onset), music_hue)
                if frame.is_beat:
                    self._spawn_random_front(p["spiral_gap"].value, music_hue)

        # --- render ----------------------------------------------------------
        value = state_to_value(self._state, self._n_excited, n_states)
        self._glow = np.maximum(value, self._glow * p["glow"].value)
        sat = state_to_sat(self._state, self._n_excited)
        out_value = self._bright * self._glow

        grid = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        for r in range(NUM_ROWS):
            for c in range(MAX_COLS):
                v = float(out_value[r, c])
                if v <= 0.004 or not VALID_MASK[r, c]:
                    continue
                s = int(self._state[r, c])
                hue = self._hue[r, c]  # the wave's own birth color
                if s > self._n_excited:  # phase shimmer across the wake
                    hue += ((s - self._n_excited) / refractory) * _HUE_WAKE_SPAN
                rr, gg, bb = colorsys.hsv_to_rgb(hue % 1.0, float(sat[r, c]), v)
                grid[r, c, 0] = rr
                grid[r, c, 1] = gg
                grid[r, c, 2] = bb

        return grid_to_leds(grid)
