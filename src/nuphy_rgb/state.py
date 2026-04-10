"""Daemon state shared between the main loop and IPC handlers."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

from nuphy_rgb.visualizer_params import VisualizerParam


class CyclicIndex:
    """Thread-safe cyclic index with an optional named-item registry.

    Tracks a current position within a fixed-size range [0, count) and
    exposes next/prev/set navigation. A changed flag is set on each mutation
    and consumed by poll_changed().

    Args:
        count: Number of positions in the cycle.
        names: Optional list of names for set_by_name() lookups. Must have
            exactly ``count`` entries if provided.
    """

    def __init__(self, count: int, names: Sequence[str] | None = None) -> None:
        if count <= 0:
            raise ValueError(f"count must be positive, got {count}")
        self._lock = threading.Lock()
        self._count = count
        self._index = 0
        self._changed = False
        self._names: list[str] | None = list(names) if names is not None else None

    @property
    def index(self) -> int:
        """Current index (read-only snapshot)."""
        with self._lock:
            return self._index

    @property
    def name(self) -> str | None:
        """Current name, or None if no names were provided."""
        with self._lock:
            if self._names is not None:
                return self._names[self._index]
            return None

    @property
    def names(self) -> list[str]:
        """All registered names (empty list if none)."""
        return list(self._names) if self._names is not None else []

    def next(self) -> None:
        """Advance to the next position, wrapping around."""
        with self._lock:
            self._index = (self._index + 1) % self._count
            self._changed = True

    def prev(self) -> None:
        """Move to the previous position, wrapping around."""
        with self._lock:
            self._index = (self._index - 1) % self._count
            self._changed = True

    def set(self, index: int) -> None:
        """Jump directly to a position.

        Args:
            index: Target index in [0, count).

        Raises:
            ValueError: If index is out of range.
        """
        # _count is immutable post-init, safe to read without lock.
        if index < 0 or index >= self._count:
            raise ValueError(f"index {index} out of range [0, {self._count})")
        with self._lock:
            self._index = index
            self._changed = True

    def set_by_name(self, name: str) -> bool:
        """Jump to the position whose name matches (case-insensitive).

        Args:
            name: Name to search for.

        Returns:
            True if found and index was updated; False if not found.

        Raises:
            ValueError: If this instance was created without names.
        """
        if self._names is None:
            raise ValueError(
                "CyclicIndex was created without names; cannot use set_by_name()"
            )
        needle = name.lower()
        with self._lock:
            for i, n in enumerate(self._names):
                if n.lower() == needle:
                    self._index = i
                    self._changed = True
                    return True
        return False

    def poll_changed(self) -> int | None:
        """Return current index if changed since last poll, else None.

        Resets the changed flag.
        """
        with self._lock:
            if self._changed:
                self._changed = False
                return self._index
            return None


class DaemonState:
    """Thread-safe state shared between the main loop and IPC server.

    Args:
        num_effects: Number of keyboard visualizer effects.
        effect_names: Names of the keyboard effects for set_by_name() support.
        num_sidelights: Number of sidelight effects (0 = sidelights disabled).
        sidelight_names: Names of sidelight effects for set_by_name() support.
    """

    def __init__(
        self,
        num_effects: int,
        effect_names: Sequence[str] | None = None,
        num_sidelights: int = 0,
        sidelight_names: Sequence[str] | None = None,
        visualizers: Sequence[Any] = (),
        side_visualizers: Sequence[Any] = (),
    ) -> None:
        self.key = CyclicIndex(num_effects, names=effect_names)
        self.side: CyclicIndex | None = (
            CyclicIndex(num_sidelights, names=sidelight_names)
            if num_sidelights > 0
            else None
        )
        self.quit_event = threading.Event()
        self._paused = False
        self._paused_changed = False
        self._pause_lock = threading.Lock()
        self._visualizers = list(visualizers)
        self._side_visualizers = list(side_visualizers)

    def _active_effect(self) -> Any | None:
        """Snapshot the currently active keyboard effect, or None."""
        if not self._visualizers:
            return None
        return self._visualizers[self.key.index]

    def _active_sidelight(self) -> Any | None:
        """Snapshot the currently active sidelight effect, or None."""
        if not self._side_visualizers or self.side is None:
            return None
        return self._side_visualizers[self.side.index]

    @staticmethod
    def _get_params(effect: Any | None) -> dict[str, VisualizerParam]:
        if effect is None:
            return {}
        return getattr(effect, "params", {})

    @staticmethod
    def _set_param(
        effect: Any | None, name: str, value: float,
    ) -> VisualizerParam:
        if effect is None:
            raise ValueError("no active effect")
        params = getattr(effect, "params", {})
        if name not in params:
            raise ValueError(f"unknown param: {name}")
        params[name].set(value)
        return params[name]

    def get_active_params(self) -> dict[str, VisualizerParam]:
        """Return the params dict for the currently active keyboard effect."""
        return self._get_params(self._active_effect())

    def set_active_param(self, name: str, value: float) -> VisualizerParam:
        """Set a param on the active keyboard effect."""
        return self._set_param(self._active_effect(), name, value)

    def get_active_side_params(self) -> dict[str, VisualizerParam]:
        """Return the params dict for the currently active sidelight effect."""
        return self._get_params(self._active_sidelight())

    def set_active_side_param(self, name: str, value: float) -> VisualizerParam:
        """Set a param on the active sidelight effect."""
        return self._set_param(self._active_sidelight(), name, value)

    @property
    def paused(self) -> bool:
        with self._pause_lock:
            return self._paused

    def set_paused(self, paused: bool) -> bool:
        """Set pause state. Returns True if state actually changed."""
        with self._pause_lock:
            if self._paused == paused:
                return False
            self._paused = paused
            self._paused_changed = True
            return True

    def poll_paused_changed(self) -> bool | None:
        """Return current paused state if changed since last poll, else None."""
        with self._pause_lock:
            if self._paused_changed:
                self._paused_changed = False
                return self._paused
            return None

    def request_quit(self) -> None:
        """Signal the main loop to exit."""
        self.quit_event.set()
