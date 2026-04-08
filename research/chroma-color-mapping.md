# Chroma-Based Color Mapping

## Problem

Current color mapping uses `freq_to_hue()` — the dominant FFT frequency bin
mapped to hue on a log scale. This is energy-based, not pitch-aware:

```text
Current pipeline:

  Audio → FFT → dominant_freq (Hz) → log scale → hue (0.0–1.0)
                     │
                 loudest bin wins
                 bass-heavy = always red
                 chords invisible
                 key changes invisible
```

A bass guitar and a kick drum both produce red. A C major chord (C+E+G)
just shows whatever note has the most energy. Harmonic movement in the
music is lost.

## What Chroma Gives Us

Chroma collapses the frequency spectrum into 12 pitch classes (C, C#, D,
..., B), summing energy across all octaves:

```text
Proposed pipeline:

  Audio → FFT magnitudes → bin to pitch class → chroma[12]
                                                    │
                              C  C# D  D# E  F  F# G  G# A  A# B
                              │                                │
                             0.0                              1.0

  130 Hz (C3) and 1046 Hz (C5) → same chroma bin
  C major chord → C, E, G bins all light up
  Key change → dominant pitch class shifts → hue shifts
```

### What It Enables

| Feature | freq_to_hue (current) | Chroma (proposed) |
|---------|----------------------|-------------------|
| Bass vs kick drum | Same color | Different pitch class |
| Chord voicing | Loudest note wins | Weighted blend of notes |
| Key changes | Invisible | Hue follows tonal center |
| Octave equivalence | Different hues | Same hue |
| Musical genres | Bass-heavy = stuck on red | Full hue range |

## How Chroma Works

### The Math

Each FFT bin at frequency `f` maps to a continuous pitch value:

```text
pitch = 12 * log2(f / f_ref)     (f_ref = C1 = 32.703 Hz)
pitch_class = pitch % 12          (0=C, 1=C#, ..., 11=B)
```

All octaves of the same note collapse to the same bin. A C at 65 Hz,
131 Hz, 262 Hz, and 523 Hz all land in pitch class 0.

### STFT vs CQT Chroma

| Approach | How it works | Pros | Cons |
|----------|-------------|------|------|
| **STFT chroma** | Fixed-resolution FFT, map bins to pitch classes via filterbank | Fast, works with our existing FFT | Low-frequency resolution (21.5 Hz bins at 48kHz/2048) |
| **CQT chroma** | Geometrically-spaced bins, equal resolution per pitch | Better accuracy at all frequencies | Expensive, complex, overkill for visualization |

**For color mapping on a keyboard, STFT chroma may be sufficient** — but
this needs empirical validation. See "FFT Resolution Deep Dive" below.

### Known Problems with Naive STFT Chroma

1. **Low-frequency resolution:** At 48kHz/2048, bin width = 23.4 Hz.
   C2→C#2 is only 4 Hz apart — they share one bin. Fix: use FFT_SIZE=4096
   (bin width = 11.7 Hz, window = 85ms, still within budget).

2. **Spectral leakage:** A pure tone spreads across adjacent bins due to
   windowing. Hann window (which we already use) is adequate.

3. **Harmonic interference:** A C3 note produces overtones at C4, G4, C5,
   E5... The G4 and E5 bleed into G and E pitch classes. This is the
   biggest quality issue.

### The Filterbank Approach (What Librosa Does)

Instead of hard-binning each FFT bin to exactly one pitch class, build a
**Gaussian filterbank matrix** (12 × N_fft) where each row is a Gaussian
centered on that pitch class's frequency bins:

```text
Filterbank (12 × N_fft):

  C  │  ╱╲                    ╱╲                    ╱╲
  C# │    ╱╲                    ╱╲                    ╱╲
  D  │      ╱╲                    ╱╲                    ╱╲
  ...│        ...                   ...
  B  │╲                    ╱╲                    ╱╲

       ──────────────────────────────────────────────────►
       0 Hz                                         24 kHz
       Each Gaussian is ~0.5 semitones wide (σ), placed at every
       octave of that pitch class. Smooth roll-off reduces leakage.
```

Chroma computation becomes one matrix multiply per frame:

```text
chroma[12] = filterbank[12 × N] @ magnitudes²[N]
```

This is what `librosa.feature.chroma_stft` does under the hood. The
filterbank is precomputed once at init — the per-frame cost is a single
`np.dot()` call (<0.1ms).

## Implementation Options

### Option A: NumPy Gaussian Filterbank (recommended, no new deps)

We already have FFT magnitudes. Build the filterbank at init, then
one matrix multiply per frame:

```python
def build_chroma_filterbank(
    n_fft: int, sr: int, n_chroma: int = 12, sigma: float = 0.5
) -> np.ndarray:
    """Build a 12 × (n_fft//2+1) Gaussian chroma filterbank."""
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    filterbank = np.zeros((n_chroma, len(freqs)))
    # Skip DC and sub-bass
    valid = freqs >= 32.0
    pitches = 12.0 * np.log2(freqs[valid] / 32.703)  # C1 reference
    for chroma_bin in range(n_chroma):
        # Distance to nearest octave of this pitch class (circular)
        distance = (pitches - chroma_bin) % 12.0
        distance = np.minimum(distance, 12.0 - distance)
        filterbank[chroma_bin, valid] = np.exp(-0.5 * (distance / sigma) ** 2)
    # Normalize each row
    row_sums = filterbank.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    filterbank /= row_sums
    return filterbank

def compute_chroma(magnitudes: np.ndarray, filterbank: np.ndarray) -> np.ndarray:
    """Compute 12-bin chroma vector. One matrix multiply."""
    energy = magnitudes ** 2
    chroma = filterbank @ energy
    # L2 normalize
    norm = np.linalg.norm(chroma)
    if norm > 0:
        chroma /= norm
    return chroma
```

Pros: No dependency, <0.1ms per frame, Gaussian smoothing handles
spectral leakage gracefully, we understand it fully.
Cons: No tuning estimation (assumes A440), no HPS for harmonic
interference — good enough for visualization.

### Option B: audioFlux (MIT license)

```python
import audioflux as af
chroma_obj = af.Chroma(num=12, radix2_exp=11, samplate=48000)
chroma = chroma_obj.chroma(audio_chunk)
```

Pros: CQT-based chroma (better frequency resolution at low pitches),
stream-designed, <1ms per frame, MIT license (safe for monetization).
Cons: New dependency.

### Option C: librosa (ISC license)

```python
import librosa
chroma = librosa.feature.chroma_stft(S=magnitudes, sr=48000)
```

Pros: Well-documented, battle-tested.
Cons: 5–15ms per frame (tight at small block sizes), designed for offline
analysis, pulls in numba/scipy.

### Recommendation

**Incremental approach — validate before investing:**

1. **Step 0: Spectral centroid on existing data** (zero work). Compute a
   weighted centroid over `AudioFrame.spectrum` (16 log-spaced bins).
   This solves "bass-heavy = always red" without any chroma computation.
   If this looks good, we may not need chroma at all.

2. **Step 1: NumPy Gaussian filterbank** (Option A). If spectral centroid
   is too coarse and we want pitch-class awareness. **Must validate with
   a sine sweep test** (C3→C4 through BlackHole) before shipping — if
   pitch class output jitters or mis-assigns at bass frequencies, skip
   to Step 2.

3. **Step 2: audioFlux CQT** (Option B). If the sine sweep reveals the
   STFT resolution problem is visually intolerable. CQT gives correct
   resolution at all octaves. MIT license is safe for monetization.

Avoid librosa for real-time chroma — designed for offline, heavy deps.
Avoid essentia — AGPL conflicts with Gumroad/app store monetization.

## Integration into AudioFrame

```python
@dataclass(frozen=True)
class AudioFrame:
    # ... existing fields ...
    chroma: tuple[float, ...] = (0.0,) * 12  # new: 12 pitch classes
```

Compute in `AudioCapture.process_latest()` alongside existing band energies:

```python
chroma = compute_chroma(magnitudes, freqs)
# Optional: smooth with ExpFilter for visual stability
chroma = self._chroma_filter.update(chroma)
```

## Chroma → Hue Mapping Strategies

### Strategy 1: Dominant Pitch Class

```python
def chroma_to_hue(chroma: np.ndarray) -> float:
    """Dominant pitch class → hue. C=0.0, B=11/12."""
    return float(np.argmax(chroma)) / 12.0
```

Simple, stable. Jumps between discrete hues. Best smoothed with ExpFilter.

### Strategy 2: Weighted Centroid

```python
def chroma_to_hue(chroma: np.ndarray) -> float:
    """Energy-weighted circular mean of pitch classes."""
    angles = np.linspace(0, 2 * np.pi, 12, endpoint=False)
    x = np.sum(chroma * np.cos(angles))
    y = np.sum(chroma * np.sin(angles))
    hue = np.arctan2(y, x) / (2 * np.pi) % 1.0
    return float(hue)
```

Smooth, continuous hue. A C major chord (C+E+G) produces a hue between
C and G rather than jumping to whichever is loudest. Musically rich.

### Strategy 3: Chroma Vector → Multi-Color

Use the full 12-bin vector to drive per-key or per-zone coloring. Each
key region gets a hue from a different pitch class. Most complex but
enables harmonic visualizations (e.g., chord diagrams on the keyboard).

## Effects That Would Benefit

| Effect | Current Color | With Chroma |
|--------|--------------|-------------|
| Color Wash | `freq_to_hue(dominant_freq)` | `chroma_to_hue(chroma)` — follows harmony |
| Interference Pond | Ripple hue from dominant freq | Ripple hue from pitch class |
| Event Horizon | Attractor colored by freq | Attractor colored by tonal center |
| Side VU Meter | N/A (proposed) | Bar color follows chroma |
| Side Beat Pulse | N/A (proposed) | Flash color follows chroma |

## Step 0: Spectral Centroid (No-Code Baseline)

Before building chroma, test whether a simpler approach solves the
"bass = always red" problem. We already have a 16-bin log-spaced
spectrum in `AudioFrame.spectrum`:

```python
def spectrum_to_hue(spectrum: tuple[float, ...]) -> float:
    """Energy-weighted centroid of existing spectrum bins → hue."""
    weights = np.array(spectrum)
    bins = np.arange(len(weights))
    total = weights.sum()
    if total < 1e-10:
        return 0.0
    return float(np.dot(weights, bins)) / (total * (len(weights) - 1))
```

No new `AudioFrame` fields, no new dependencies. If this looks good,
chroma may be unnecessary for our use case.

## FFT Resolution Deep Dive

The core limitation of STFT chroma at bass frequencies. This is a
**structural accuracy problem**, not noise — smoothing cannot fix it.

```text
Note    Freq      Semitone gap    Bins/semitone (48kHz/2048)    (48kHz/4096)
──────────────────────────────────────────────────────────────────────────────
C2       65 Hz       3.9 Hz       0.17                          0.33
C3      131 Hz       7.8 Hz       0.33                          0.67
C4      262 Hz      15.6 Hz       0.67                          1.3
C5      523 Hz      31.2 Hz       1.3                           2.7
C6     1046 Hz      62.4 Hz       2.7                           5.3
```

Below C5, each semitone occupies less than one FFT bin. The Gaussian
filterbank helps (smooth roll-off between bins) but cannot create
resolution that doesn't exist in the data. Even FFT_SIZE=4096 only
marginally helps at C3.

**Validation required:** Run a sine sweep C3→C4 through BlackHole and
log pitch class output per frame. If output is stable and monotonic,
STFT chroma is acceptable for visualization. If it jitters, skip to
audioFlux CQT.

## Open Questions

1. **Chord-following vs key-following:** These are different goals with
   different smoothing constants:

   | Goal | Smoothing | Behavior |
   |------|-----------|----------|
   | Follow current chord | Fast (per-frame, α~0.5) | Reactive, jumpy |
   | Follow key of the music | Slow (2-5 sec average, α~0.05) | Stable, gradual |

   A 12-bar blues stays in one key, but frame-by-frame chroma jumps
   around chord tones. Pick one as default. Recommend **weighted centroid
   with moderate smoothing** (α~0.3) as a compromise.

2. **Silence handling:** When RMS drops below threshold, chroma is noise.
   Gate it using `raw_rms` (not AGC-normalized `rms`, which never
   approaches zero). Consider a shared `is_silent` flag on AudioFrame
   rather than per-feature silence gates.

3. **Mapping strategy:** Weighted centroid is the recommended default —
   continuous, works for both monophonic and polyphonic content. Dominant
   pitch class (argmax) is available as an alternative for effects that
   want discrete hue steps. The centroid can produce musically ambiguous
   hues for complex chords, but for RGB visualization this is acceptable.

4. **FFT size for chroma:** Could use a separate larger FFT (4096 or
   8192) for chroma while keeping 2048 for band energies and beat
   detection. Adds complexity but decouples latency requirements.

5. **Harmonic Product Spectrum:** If overtone bleed is visually noticeable,
   HPS suppresses harmonics. Test without it first — for color mapping,
   Gaussian filterbank alone may be sufficient.

6. **AudioFrame field accumulation:** Currently 12 fields, chroma would
   add a 13th. Fields fall into distinct groups (energy, transients,
   spectral, harmonic). Not urgent, but worth noting the God Object
   trajectory — consider grouping if we add more features.
