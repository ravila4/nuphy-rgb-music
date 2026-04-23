"""Auto-switch effects on tonal transitions (Milkdrop-style shuffle mode)."""

from __future__ import annotations

from nuphy_rgb.audio import AudioFrame
from nuphy_rgb.state import DaemonState


class ShuffleManager:
    """Auto-switches the active effect when the music transitions.

    The caller invokes update() each frame. When state.shuffle_enabled and
    tonal_change exceeds threshold for hysteresis_frames consecutive frames
    AND min_dwell_s has elapsed since the last switch, the next non-excluded
    effect is activated via state.key.set().
    """

    def __init__(
        self,
        threshold: float = 0.05,
        min_dwell_s: float = 15.0,
        hysteresis_frames: int = 3,
        excluded_names: tuple[str, ...] = ("Blackout",),
    ):
        self._threshold = threshold
        self._min_dwell_s = min_dwell_s
        self._hysteresis_frames = hysteresis_frames
        self._excluded = {n.lower() for n in excluded_names}
        self._consecutive_above = 0
        self._last_switch_t = float("-inf")

    @property
    def excluded_names(self) -> frozenset[str]:
        """Lowercased names of effects that shuffle will never pick."""
        return frozenset(self._excluded)

    def update(self, frame: AudioFrame, state: DaemonState) -> bool:
        """Feed one frame. Returns True iff an effect switch was triggered."""
        if not state.shuffle_enabled:
            self._consecutive_above = 0
            return False

        if frame.tonal_change > self._threshold:
            self._consecutive_above += 1
        else:
            self._consecutive_above = 0

        if self._consecutive_above < self._hysteresis_frames:
            return False

        if frame.timestamp - self._last_switch_t < self._min_dwell_s:
            return False

        next_idx = self._next_eligible_index(state)
        if next_idx is None:
            return False

        state.key.set(next_idx)
        self._last_switch_t = frame.timestamp
        self._consecutive_above = 0
        return True

    def _next_eligible_index(self, state: DaemonState) -> int | None:
        """Return the next cyclic index whose name isn't excluded."""
        names = state.key.names
        count = len(names)
        if count == 0:
            return None
        start = state.key.index
        for offset in range(1, count + 1):
            idx = (start + offset) % count
            if idx == start:
                break  # full loop, nothing eligible
            if names[idx].lower() not in self._excluded:
                return idx
        return None
