from nuphy_rgb.audio import AudioFrame


def make_frame(**kwargs) -> AudioFrame:
    """Build an AudioFrame with sensible defaults for testing."""
    defaults = dict(
        bass=0.0, mids=0.0, highs=0.0,
        dominant_freq=0.0, rms=0.0, is_beat=False, timestamp=0.0,
    )
    defaults.update(kwargs)
    defaults.setdefault("raw_rms", defaults["rms"])
    return AudioFrame(**defaults)
