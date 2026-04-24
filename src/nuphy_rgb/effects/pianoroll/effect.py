"""Pianoroll: piano-roll visualization of the detected pitch contour.

Columns span a 16-semitone chromatic window. The detected pitch lights
the matching column in the bottom row; rows above hold the history,
scrolling upward over time. Pitch class drives hue, voiced probability
drives brightness, so silence fades the keyboard.

Tracks the dominant periodic voice — usually bass on polyphonic music.
A wide-range YIN detector on the raw signal gives a nearly-continuous
pitch stream, which reads as a coherent melodic contour on the grid.
"""

import colorsys

import numpy as np

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.effects.grid import MAX_COLS, NUM_ROWS, grid_to_leds

WINDOW_SPAN = MAX_COLS                 # 16 semitones visible at once
DEFAULT_WINDOW_BASE = 48               # C3..D#4 by default
SCROLL_EVERY_N_FRAMES = 3              # ~100ms per row at 30fps
ROW_DECAY = 0.80                       # each older row dims further
NEW_NOTE_THRESHOLD = 0.25              # voiced_prob required to stamp a note
VOICED_SMOOTHING_RISE = 0.7
VOICED_SMOOTHING_DECAY = 0.2


class Pianoroll:
    """Scrolling piano-roll of the detected pitch contour."""

    name = "Pianoroll"
    description = (
        "Pretends the keyboard is a piano and plays the dominant pitched "
        "voice. Bottom row is the current note; history scrolls upward. "
        "Color by pitch class, brightness by voicing confidence."
    )

    def __init__(self) -> None:
        # Per-cell brightness [0, 1]
        self._brightness = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        # Per-cell MIDI note number so hue survives window shifts.
        # 0.0 means "empty".
        self._pitch = np.zeros((NUM_ROWS, MAX_COLS), dtype=np.float64)
        self._window_base = DEFAULT_WINDOW_BASE
        self._frame_count = 0
        # Smooth voiced_prob so ephemeral blips don't stamp phantom notes.
        self._voiced_ema: float = 0.0

    def _shift_window_if_needed(self, midi: float) -> None:
        """Octave-shift the window by ±12 until midi lands inside it."""
        while midi < self._window_base:
            self._window_base -= 12
        while midi >= self._window_base + WINDOW_SPAN:
            self._window_base += 12

    def _scroll_up(self) -> None:
        """Drop the top row, shift everything up, fade with row decay."""
        self._brightness[:-1] = self._brightness[1:] * ROW_DECAY
        self._pitch[:-1] = self._pitch[1:]
        self._brightness[-1] = 0.0
        self._pitch[-1] = 0.0

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        # Smooth voiced probability (asymmetric: fast attack, slow decay).
        if frame.voiced_prob > self._voiced_ema:
            alpha = VOICED_SMOOTHING_RISE
        else:
            alpha = VOICED_SMOOTHING_DECAY
        self._voiced_ema = alpha * frame.voiced_prob + (1 - alpha) * self._voiced_ema

        # Periodic scroll so history shows up on the grid instead of
        # collapsing into a single row.
        self._frame_count += 1
        if self._frame_count % SCROLL_EVERY_N_FRAMES == 0:
            self._scroll_up()

        # Stamp the current note, if voicing is confident enough.
        if frame.pitch_midi > 0.0 and self._voiced_ema >= NEW_NOTE_THRESHOLD:
            self._shift_window_if_needed(frame.pitch_midi)
            col = int(round(frame.pitch_midi - self._window_base))
            col = max(0, min(MAX_COLS - 1, col))
            self._brightness[-1, col] = max(
                self._brightness[-1, col], self._voiced_ema
            )
            self._pitch[-1, col] = frame.pitch_midi
        else:
            # Unvoiced frame: fade the current row so silence drops out
            # visibly even between scrolls.
            self._brightness[-1] *= 0.85

        # Render: color by true pitch class, brightness from the stored grid.
        rgb = np.zeros((NUM_ROWS, MAX_COLS, 3), dtype=np.float64)
        for row in range(NUM_ROWS):
            for col in range(MAX_COLS):
                b = self._brightness[row, col]
                if b < 0.01:
                    continue
                pitch_class = int(round(self._pitch[row, col])) % 12
                hue = pitch_class / 12.0
                r, g, bl = colorsys.hsv_to_rgb(hue, 0.85, min(1.0, b))
                rgb[row, col] = (r, g, bl)

        return grid_to_leds(rgb)
