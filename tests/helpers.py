from nuphy_rgb.audio import AudioFrame, NUM_CHROMA_BINS, NUM_SPECTRUM_BINS


def make_frame(**kwargs) -> AudioFrame:
    """Build an AudioFrame with sensible defaults for testing."""
    defaults = dict(
        bass=0.0, mids=0.0, highs=0.0,
        dominant_freq=0.0, rms=0.0, is_beat=False, timestamp=0.0,
        onset_strength=0.0, spectral_flux=0.0,
        mid_beat=False, high_beat=False,
        spectrum=(0.0,) * NUM_SPECTRUM_BINS,
        chroma=(0.0,) * NUM_CHROMA_BINS,
        spectral_centroid=0.0,
        spectral_flatness=0.0,
    )
    defaults.update(kwargs)
    # raw_rms (pre-AGC) defaults to rms for convenience in tests.
    defaults.setdefault("raw_rms", defaults["rms"])
    return AudioFrame(**defaults)
