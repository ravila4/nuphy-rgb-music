"""Per-effect parameter persistence.

User-overridden visualizer parameter values live under
``~/.config/nuphy-rgb/params/<effect>.json`` as a flat ``{name: value}``
dict. The daemon loads these at startup and applies them to the matching
``VisualizerParam`` objects before IPC opens. The Swift GUI is the only
writer; the daemon only reads.

Missing files are not an error — they mean "no overrides, use defaults."
Malformed files are logged and treated as missing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def params_dir() -> Path:
    """Directory holding per-effect override JSON files."""
    return Path.home() / ".config" / "nuphy-rgb" / "params"


def load_effect_params(effect_name: str) -> dict[str, float]:
    """Return user overrides for one effect, or ``{}`` if none exist."""
    path = params_dir() / f"{effect_name}.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("failed to read overrides for %s: %s", effect_name, exc)
        return {}
    if not isinstance(raw, dict):
        log.warning("overrides for %s are not a dict, ignoring", effect_name)
        return {}
    return {str(k): float(v) for k, v in raw.items()}


def apply_overrides_to_visualizers(visualizers) -> None:
    """Load per-effect overrides from disk and apply them in place.

    Unknown param names and out-of-range values are skipped with a
    warning; startup must never fail because of a stale or corrupt
    override file. Visualizers without a ``params`` attribute are
    silently ignored.
    """
    for viz in visualizers:
        name = getattr(viz, "name", None)
        if not name:
            continue
        params = getattr(viz, "params", None)
        if not params:
            continue
        overrides = load_effect_params(name)
        for key, value in overrides.items():
            p = params.get(key)
            if p is None:
                log.warning("skipping unknown param %s.%s", name, key)
                continue
            try:
                p.set(value)
            except ValueError as exc:
                log.warning("skipping %s.%s: %s", name, key, exc)
