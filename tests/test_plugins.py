"""Tests for plugin discovery system."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from nuphy_rgb.plugins import (
    _has_render_protocol,
    _load_classes_from_file,
    _scan_directory,
    discover_effects,
    discover_sidelights,
)


# -- _has_render_protocol -----------------------------------------------------


class _GoodEffect:
    name = "Good"

    def render(self, frame):
        return []


class _NoName:
    def render(self, frame):
        return []


class _NameNotStr:
    name = 42

    def render(self, frame):
        return []


class _NoRender:
    name = "Missing render"


class _RenderWrongArity:
    name = "Bad"

    def render(self):  # missing frame
        return []


class TestHasRenderProtocol:
    def test_valid_class(self):
        assert _has_render_protocol(_GoodEffect) is True

    def test_missing_name(self):
        assert _has_render_protocol(_NoName) is False

    def test_name_not_str(self):
        assert _has_render_protocol(_NameNotStr) is False

    def test_missing_render(self):
        assert _has_render_protocol(_NoRender) is False

    def test_render_wrong_arity(self):
        assert _has_render_protocol(_RenderWrongArity) is False


# -- _load_classes_from_file --------------------------------------------------


def _write_effect(path: Path, name: str = "TestEffect") -> Path:
    """Write a minimal valid effect .py file and return its path."""
    path.write_text(
        f"class {name}:\n"
        f'    name = "{name}"\n'
        f"    def render(self, frame):\n"
        f"        return [(0, 0, 0)]\n"
    )
    return path


class TestLoadClassesFromFile:
    def test_single_valid_class(self, tmp_path: Path):
        f = _write_effect(tmp_path / "glow.py")
        classes = _load_classes_from_file(f)
        assert len(classes) == 1
        assert classes[0]().name == "TestEffect"

    def test_two_valid_classes(self, tmp_path: Path):
        f = tmp_path / "duo.py"
        f.write_text(
            'class A:\n    name = "A"\n    def render(self, frame): return []\n'
            'class B:\n    name = "B"\n    def render(self, frame): return []\n'
        )
        classes = _load_classes_from_file(f)
        assert len(classes) == 2
        names = {c().name for c in classes}
        assert names == {"A", "B"}

    def test_mixed_valid_and_invalid(self, tmp_path: Path):
        f = tmp_path / "mix.py"
        f.write_text(
            'class Good:\n    name = "Good"\n    def render(self, frame): return []\n'
            "class Bad:\n    pass\n"
        )
        classes = _load_classes_from_file(f)
        assert len(classes) == 1
        assert classes[0]().name == "Good"

    def test_syntax_error_returns_empty(self, tmp_path: Path, caplog):
        f = tmp_path / "broken.py"
        f.write_text("def oops(\n")
        with caplog.at_level(logging.WARNING):
            classes = _load_classes_from_file(f)
        assert classes == []
        assert "Failed to load plugin" in caplog.text

    def test_import_error_returns_empty(self, tmp_path: Path, caplog):
        f = tmp_path / "bad_import.py"
        f.write_text("import nonexistent_module_xyz\n")
        with caplog.at_level(logging.WARNING):
            classes = _load_classes_from_file(f)
        assert classes == []

    def test_no_classes_returns_empty(self, tmp_path: Path):
        f = tmp_path / "empty.py"
        f.write_text("x = 42\n")
        assert _load_classes_from_file(f) == []

    def test_no_module_collision(self, tmp_path: Path):
        """Two files with the same stem in different dirs get unique modules."""
        dir_a = tmp_path / "pack_a"
        dir_b = tmp_path / "pack_b"
        dir_a.mkdir()
        dir_b.mkdir()
        _write_effect(dir_a / "ripple.py", name="RippleA")
        _write_effect(dir_b / "ripple.py", name="RippleB")
        classes_a = _load_classes_from_file(dir_a / "ripple.py")
        classes_b = _load_classes_from_file(dir_b / "ripple.py")
        assert classes_a[0]().name == "RippleA"
        assert classes_b[0]().name == "RippleB"


# -- _scan_directory ----------------------------------------------------------


class TestScanDirectory:
    def test_finds_py_files(self, tmp_path: Path):
        _write_effect(tmp_path / "a.py", name="A")
        _write_effect(tmp_path / "b.py", name="B")
        classes = _scan_directory(tmp_path)
        names = {c().name for c in classes}
        assert names == {"A", "B"}

    def test_skips_underscore_prefixed(self, tmp_path: Path):
        _write_effect(tmp_path / "_helper.py", name="Helper")
        _write_effect(tmp_path / "real.py", name="Real")
        classes = _scan_directory(tmp_path)
        assert len(classes) == 1
        assert classes[0]().name == "Real"

    def test_skips_init(self, tmp_path: Path):
        _write_effect(tmp_path / "__init__.py", name="Init")
        assert _scan_directory(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path: Path):
        assert _scan_directory(tmp_path / "nope") == []

    def test_non_py_files_ignored(self, tmp_path: Path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "data.json").write_text("{}")
        _write_effect(tmp_path / "real.py", name="Real")
        classes = _scan_directory(tmp_path)
        assert len(classes) == 1

    def test_recursive_into_subdirs(self, tmp_path: Path):
        sub = tmp_path / "my-pack"
        sub.mkdir()
        _write_effect(tmp_path / "loose.py", name="Loose")
        _write_effect(sub / "packed.py", name="Packed")
        classes = _scan_directory(tmp_path)
        names = {c().name for c in classes}
        assert names == {"Loose", "Packed"}


# -- discover_effects / discover_sidelights -----------------------------------


class TestDiscoverEffects:
    def test_empty_config_dir(self, tmp_path: Path):
        assert discover_effects(config_dir=tmp_path) == []

    def test_nonexistent_config_dir(self, tmp_path: Path):
        assert discover_effects(config_dir=tmp_path / "nope") == []

    def test_discovers_from_effects_dir(self, tmp_path: Path):
        effects = tmp_path / "effects"
        effects.mkdir()
        _write_effect(effects / "glow.py", name="Glow")
        classes = discover_effects(config_dir=tmp_path)
        assert len(classes) == 1
        assert classes[0]().name == "Glow"

    def test_discovers_from_subdirectory_pack(self, tmp_path: Path):
        pack = tmp_path / "effects" / "spectral-pack"
        pack.mkdir(parents=True)
        _write_effect(pack / "aurora.py", name="Aurora")
        classes = discover_effects(config_dir=tmp_path)
        assert len(classes) == 1
        assert classes[0]().name == "Aurora"


class TestDiscoverSidelights:
    def test_discovers_from_sidelights_dir(self, tmp_path: Path):
        sl = tmp_path / "sidelights"
        sl.mkdir()
        _write_effect(sl / "pulse.py", name="Pulse")
        classes = discover_sidelights(config_dir=tmp_path)
        assert len(classes) == 1
        assert classes[0]().name == "Pulse"

    def test_empty_returns_empty(self, tmp_path: Path):
        assert discover_sidelights(config_dir=tmp_path) == []
