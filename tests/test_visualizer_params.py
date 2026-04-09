"""Tests for VisualizerParam dataclass."""

import threading

import pytest

from nuphy_rgb.visualizer_params import VisualizerParam


class TestSet:
    def test_set_valid_value(self):
        p = VisualizerParam(value=0.5, default=0.5, min=0.0, max=1.0)
        p.set(0.7)
        assert p.get() == 0.7

    def test_set_at_min_boundary(self):
        p = VisualizerParam(value=0.5, default=0.5, min=0.0, max=1.0)
        p.set(0.0)
        assert p.get() == 0.0

    def test_set_at_max_boundary(self):
        p = VisualizerParam(value=0.5, default=0.5, min=0.0, max=1.0)
        p.set(1.0)
        assert p.get() == 1.0

    def test_set_below_min_raises(self):
        p = VisualizerParam(value=0.5, default=0.5, min=0.0, max=1.0)
        with pytest.raises(ValueError, match="out of range"):
            p.set(-0.1)
        assert p.get() == 0.5  # unchanged

    def test_set_above_max_raises(self):
        p = VisualizerParam(value=0.5, default=0.5, min=0.0, max=1.0)
        with pytest.raises(ValueError, match="out of range"):
            p.set(1.1)
        assert p.get() == 0.5  # unchanged


class TestReset:
    def test_reset_restores_default(self):
        p = VisualizerParam(value=0.5, default=0.5, min=0.0, max=1.0)
        p.set(0.9)
        p.reset()
        assert p.get() == 0.5


class TestToDict:
    def test_to_dict_fields(self):
        p = VisualizerParam(
            value=0.7, default=0.5, min=0.0, max=1.0,
            description="test param",
        )
        d = p.to_dict()
        assert d == {
            "value": 0.7,
            "default": 0.5,
            "min": 0.0,
            "max": 1.0,
            "description": "test param",
        }

    def test_to_dict_reflects_mutations(self):
        p = VisualizerParam(value=0.5, default=0.5, min=0.0, max=1.0)
        p.set(0.8)
        assert p.to_dict()["value"] == 0.8


class TestThreadSafety:
    def test_concurrent_set_and_get(self):
        """Verify no exceptions under concurrent access."""
        p = VisualizerParam(value=0.5, default=0.5, min=0.0, max=1.0)
        errors: list[Exception] = []

        def writer():
            try:
                for _ in range(1000):
                    p.set(0.7)
                    p.set(0.3)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(1000):
                    v = p.get()
                    assert 0.0 <= v <= 1.0
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
