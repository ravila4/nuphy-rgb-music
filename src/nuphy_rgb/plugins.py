"""Plugin discovery for user-installed effects and sidelight visualizers.

Scans ``~/.config/nuphy-rgb/effects/`` and ``~/.config/nuphy-rgb/sidelights/``
(recursively) for ``.py`` files containing classes that satisfy the
:class:`~nuphy_rgb.visualizer.Visualizer` or
:class:`~nuphy_rgb.sidelights.visualizer.SideLightVisualizer` protocol.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "nuphy-rgb"


def _has_render_protocol(cls: type) -> bool:
    """Check if *cls* has a ``name`` str attribute and a ``render(self, frame)`` method."""
    if not isinstance(getattr(cls, "name", None), str):
        return False
    render = getattr(cls, "render", None)
    if render is None or not callable(render):
        return False
    sig = inspect.signature(render)
    # Expect (self, frame) — exactly 2 parameters
    params = list(sig.parameters.values())
    return len(params) == 2


def _module_name_for(path: Path) -> str:
    """Unique module name derived from the absolute path to avoid sys.modules collisions."""
    digest = hashlib.md5(str(path.resolve()).encode()).hexdigest()[:8]
    return f"nuphy_plugin_{path.stem}_{digest}"


def _load_classes_from_file(path: Path) -> list[type]:
    """Import a ``.py`` file and return all classes satisfying the visualizer protocol."""
    module_name = _module_name_for(path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        log.warning("Could not create module spec for %s", path)
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        log.warning("Failed to load plugin %s", path, exc_info=True)
        del sys.modules[module_name]
        return []
    classes: list[type] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ == module_name and _has_render_protocol(obj):
            classes.append(obj)
    return classes


def _scan_directory(directory: Path) -> list[type]:
    """Recursively scan *directory* for ``.py`` files and return matching classes.

    Skips files whose name starts with ``_`` (helpers, ``__init__``, etc.).
    """
    if not directory.is_dir():
        return []
    classes: list[type] = []
    for py_file in sorted(directory.rglob("*.py")):
        if py_file.stem.startswith("_"):
            continue
        classes.extend(_load_classes_from_file(py_file))
    return classes


def discover_effects(config_dir: Path | None = None) -> list[type]:
    """Discover plugin keyboard effects from ``config_dir/effects/``."""
    return _scan_directory((config_dir or DEFAULT_CONFIG_DIR) / "effects")


def discover_sidelights(config_dir: Path | None = None) -> list[type]:
    """Discover plugin sidelight effects from ``config_dir/sidelights/``."""
    return _scan_directory((config_dir or DEFAULT_CONFIG_DIR) / "sidelights")
