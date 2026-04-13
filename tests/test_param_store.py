"""Tests for param_store module."""

import json
from pathlib import Path

import pytest

from nuphy_rgb import param_store


@pytest.fixture()
def tmp_params_dir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "params"
    monkeypatch.setattr(param_store, "params_dir", lambda: d)
    return d


class TestLoadEffectParams:
    def test_missing_file_returns_empty(self, tmp_params_dir) -> None:
        assert param_store.load_effect_params("Fancy") == {}

    def test_missing_dir_returns_empty(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            param_store, "params_dir", lambda: tmp_path / "nope" / "params"
        )
        assert param_store.load_effect_params("Fancy") == {}

    def test_reads_valid_file(self, tmp_params_dir) -> None:
        tmp_params_dir.mkdir(parents=True)
        (tmp_params_dir / "Fancy.json").write_text(
            json.dumps({"speed": 0.8, "chaos": 0.3})
        )
        result = param_store.load_effect_params("Fancy")
        assert result == {"speed": 0.8, "chaos": 0.3}

    def test_malformed_json_returns_empty(self, tmp_params_dir, caplog) -> None:
        tmp_params_dir.mkdir(parents=True)
        (tmp_params_dir / "Fancy.json").write_text("{not json")
        with caplog.at_level("WARNING"):
            assert param_store.load_effect_params("Fancy") == {}
        assert any("Fancy" in r.message for r in caplog.records)

    def test_non_dict_root_returns_empty(self, tmp_params_dir) -> None:
        tmp_params_dir.mkdir(parents=True)
        (tmp_params_dir / "Fancy.json").write_text("[1, 2, 3]")
        assert param_store.load_effect_params("Fancy") == {}

    def test_effect_name_with_space(self, tmp_params_dir) -> None:
        tmp_params_dir.mkdir(parents=True)
        (tmp_params_dir / "Strange Attractor.json").write_text(
            json.dumps({"chaos": 0.5})
        )
        assert param_store.load_effect_params("Strange Attractor") == {"chaos": 0.5}


class TestParamsDir:
    def test_returns_dot_config_path(self) -> None:
        d = param_store.params_dir()
        assert d.name == "params"
        assert d.parent.name == "nuphy-rgb"
        assert d.parent.parent.name == ".config"


class _FakeViz:
    def __init__(self, name: str, params: dict | None = None) -> None:
        self.name = name
        if params is not None:
            self.params = params


class TestApplyOverridesToVisualizers:
    def test_applies_known_overrides(self, tmp_params_dir) -> None:
        from nuphy_rgb.visualizer_params import VisualizerParam
        tmp_params_dir.mkdir(parents=True)
        (tmp_params_dir / "Fancy.json").write_text(
            json.dumps({"speed": 0.8})
        )
        viz = _FakeViz("Fancy", {
            "speed": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
            ),
        })
        param_store.apply_overrides_to_visualizers([viz])
        assert viz.params["speed"].get() == 0.8

    def test_skips_unknown_param(self, tmp_params_dir, caplog) -> None:
        from nuphy_rgb.visualizer_params import VisualizerParam
        tmp_params_dir.mkdir(parents=True)
        (tmp_params_dir / "Fancy.json").write_text(
            json.dumps({"unknown": 0.8})
        )
        viz = _FakeViz("Fancy", {
            "speed": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
            ),
        })
        with caplog.at_level("WARNING"):
            param_store.apply_overrides_to_visualizers([viz])
        assert viz.params["speed"].get() == 0.5
        assert any("unknown" in r.message for r in caplog.records)

    def test_skips_out_of_range(self, tmp_params_dir, caplog) -> None:
        from nuphy_rgb.visualizer_params import VisualizerParam
        tmp_params_dir.mkdir(parents=True)
        (tmp_params_dir / "Fancy.json").write_text(
            json.dumps({"speed": 99.0})
        )
        viz = _FakeViz("Fancy", {
            "speed": VisualizerParam(
                value=0.5, default=0.5, min=0.0, max=1.0,
            ),
        })
        with caplog.at_level("WARNING"):
            param_store.apply_overrides_to_visualizers([viz])
        assert viz.params["speed"].get() == 0.5

    def test_no_params_attribute_is_ignored(self, tmp_params_dir) -> None:
        viz = _FakeViz("Plain")
        param_store.apply_overrides_to_visualizers([viz])  # no crash
