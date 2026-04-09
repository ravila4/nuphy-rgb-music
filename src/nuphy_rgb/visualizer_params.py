"""Typed, named parameters that visualizer effects can expose for runtime tuning."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(eq=False)
class VisualizerParam:
    """A single tunable parameter with range validation and thread safety.

    Effects declare these in a ``params`` dict to expose knobs for live
    adjustment via IPC.  The lock protects ``value`` against concurrent
    reads (render thread) and writes (IPC thread).
    """

    value: float
    default: float
    min: float
    max: float
    description: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set(self, v: float) -> None:
        """Set value, raising ValueError if *v* is outside [min, max]."""
        # min/max are immutable post-init; no lock needed for the range check.
        if v < self.min or v > self.max:
            raise ValueError(
                f"value {v} out of range [{self.min}, {self.max}]"
            )
        with self._lock:
            self.value = v

    def reset(self) -> None:
        """Reset value to the default."""
        with self._lock:
            self.value = self.default

    def get(self) -> float:
        """Thread-safe read of the current value."""
        with self._lock:
            return self.value

    def to_dict(self) -> dict:
        """JSON-serializable representation for IPC responses."""
        with self._lock:
            v = self.value
        return {
            "value": v,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "description": self.description,
        }
