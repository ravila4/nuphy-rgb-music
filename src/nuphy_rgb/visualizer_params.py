"""Typed, named parameters that visualizer effects can expose for runtime tuning."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(eq=False)
class VisualizerParam:
    """A single tunable parameter with range validation."""

    value: float
    default: float
    min: float
    max: float
    description: str = ""
    order: int = 0

    def set(self, v: float) -> None:
        if v < self.min or v > self.max:
            raise ValueError(
                f"value {v} out of range [{self.min}, {self.max}]"
            )
        self.value = v

    def reset(self) -> None:
        self.value = self.default

    def get(self) -> float:
        return self.value

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "description": self.description,
            "order": self.order,
        }
