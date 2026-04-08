# Side LED Effect Architecture

## Context

We now have host-controlled side LED streaming (commands 0x28–0x2A).
12 WS2812 LEDs: 6 left (indices 0–5, top to bottom) + 6 right (6–11).
This document proposes the architecture for side LED effects and how
they integrate into the existing visualizer pipeline.

## Design: Independent n × m Effect Matrix

Side effects and keyboard effects are **independent and combinatorial**.
Any keyboard effect can pair with any side effect:

```text
                       Side Effects (Ctrl+Shift+Up/Down)
                       ──────────────────────────────────
                        Off   VU    Wave  Rainbow  Beat
                       ┌─────┬─────┬─────┬───────┬─────┐
  Keyboard  Color Wash │ a,0 │ a,1 │ a,2 │  a,3  │ a,4 │
  Effects   Interfer.  │ b,0 │ b,1 │ b,2 │  b,3  │ b,4 │
  (Ctrl+    Mycelium   │ c,0 │ c,1 │ c,2 │  c,3  │ c,4 │
  Shift+    Evt Horiz  │ d,0 │ d,1 │ d,2 │  d,3  │ d,4 │
  Left/     Str Attr   │ e,0 │ e,1 │ e,2 │  e,3  │ e,4 │
  Right)    Waterfall  │ f,0 │ f,1 │ f,2 │  f,3  │ f,4 │
            Off        │ g,0 │ g,1 │ g,2 │  g,3  │ g,4 │
                       └─────┴─────┴─────┴───────┴─────┘

  6 key effects × 5 side effects = 30 combinations (+ off × off)
```

Both use the same `AudioFrame` — they naturally sync without coupling.
The "Off" entry in each list lets you run only one or neither.

## Architecture Options

### Option A: SideVisualizer Protocol (mirrors Visualizer)

```python
class SideVisualizer(Protocol):
    name: str
    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]: ...
    # Returns exactly 12 RGB tuples (SIDE_LED_COUNT)
```

Each side effect is its own class. Registered in `ALL_SIDE_EFFECTS`.
Main loop calls `side_viz.render(frame)` independently.

```text
main loop:
  frame = audio.process_latest()
  key_colors = key_visualizers[key_idx].render(frame)     # 84 LEDs
  side_colors = side_visualizers[side_idx].render(frame)   # 12 LEDs
  send_frame(dev, key_colors)
  send_side_frame(dev, side_colors)
```

Pros:

- Same pattern as keyboard effects — familiar, testable
- Each effect is self-contained with its own state (filters, timers)
- Plugin system: drop in a .py file with a class that has `name` + `render()`
- Easy to test in simulation

Cons:

- Some side effects are <20 lines — a full class feels heavy
- Proliferation of tiny files in `effects/`

### Option B: Side Effects as Functions

```python
SideEffectFn = Callable[[AudioFrame], list[tuple[int, int, int]]]

def vu_meter(frame: AudioFrame) -> list[tuple[int, int, int]]: ...
def wave(frame: AudioFrame) -> list[tuple[int, int, int]]: ...
def rainbow(frame: AudioFrame) -> list[tuple[int, int, int]]: ...

ALL_SIDE_EFFECTS = [vu_meter, wave, rainbow, beat_pulse]
```

Pros:

- Minimal boilerplate for simple effects
- All side effects could live in one file

Cons:

- No per-instance state without closures or global mutable state
- Breaks the plugin pattern (classes are easier to discover/register)
- Stateful effects (wave phase, filter state) get awkward

### Option C: Single SideVisualizer Class with Modes

```python
class SideVisualizer:
    modes = ["Off", "VU Meter", "Wave", "Rainbow", "Beat Pulse"]

    def __init__(self):
        self.mode_index = 0
        # shared state for all modes

    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]:
        match self.modes[self.mode_index]:
            case "VU Meter": return self._vu_meter(frame)
            case "Wave": return self._wave(frame)
            ...
```

Pros:

- One class, one file, simple
- Shared state across modes (filters, timers)

Cons:

- God class risk — grows unbounded as effects are added
- Can't add effects without modifying the class (closed for extension)
- Breaks plugin/drop-in pattern
- Harder to test individual effects in isolation

### Recommendation

**Option A** (SideVisualizer protocol). It's the same pattern we already
use for keyboard effects, which means:

- The plugin system we're planning works identically for both
- Effects are testable in isolation
- New effects are additive (open for extension)
- The "tiny class" concern is a non-issue — a 20-line class with `name`
  and `render()` is perfectly readable

Side effects live in `src/nuphy_rgb/side_effects/` (parallel to `effects/`).

## Main Loop Integration

```python
# main.py — updated render loop

with ExitStack() as stack:
    for dev, _ in devices:
        stack.enter_context(streaming_mode(dev))
        stack.enter_context(side_streaming_mode(dev))  # NEW

    while not state.quit:
        frame = audio.process_latest()
        if frame is not None:
            last_colors = key_visualizers[state.key_idx].render(frame)
            last_side = side_visualizers[state.side_idx].render(frame)

        for dev, _ in devices:
            send_frame(dev, last_colors)
            send_side_frame(dev, last_side)          # NEW
```

## Hotkey Changes

```python
# Existing
"<ctrl>+<shift>+<right>":  next keyboard effect
"<ctrl>+<shift>+<left>":   prev keyboard effect
"<ctrl>+<shift>+q":        quit

# New
"<ctrl>+<shift>+<up>":     next side effect
"<ctrl>+<shift>+<down>":   prev side effect
```

`_HotkeyState` gains `side_idx` alongside `viz_index`, plus
`next_side_effect()` / `prev_side_effect()` methods.

## Proposed Side Effects

### 1. Off

Returns 12x (0, 0, 0). Trivial but necessary for the matrix.

### 2. VU Meter

```text
  LEFT (bass)              RIGHT (treble)
  ┌───┐                    ┌───┐
  │   │ 5  ░░░             │   │ 11  ░░░
  │   │ 4  ░░░             │   │ 10  ░░░
  │ ▓ │ 3  ▓▓▓  ← peak     │ ▓ │  9  ▓▓▓
  │ █ │ 2  ███             │ █ │  8  ███
  │ █ │ 1  ███             │ █ │  7  ███
  │ █ │ 0  ███             │ █ │  6  ███
  └───┘                    └───┘

  Fill from bottom (index 5→0 left, 11→6 right)
  Left level = bass energy, Right level = treble energy
  Neutral = dim white, active = colored by chroma (when available)
  Peak hold with slow decay
```

Maps `frame.bass` → left fill level (0–6 LEDs), `frame.highs` → right.
Color from `freq_to_hue()` or chroma when available.

### 3. 1D Wave

```text
  LEFT           RIGHT
  ┌───┐          ┌───┐
  │ ░ │ 5        │ █ │ 11
  │ █ │ 4        │ ░ │ 10    sine wave scrolling downward
  │ ░ │ 3        │   │  9    amplitude = RMS
  │   │ 2        │ ░ │  8    wavelength = dominant_freq mapped
  │ ░ │ 1        │ █ │  7    color = freq_to_hue or chroma
  │ █ │ 0        │ ░ │  6    right = mirrored or phase-shifted
  └───┘          └───┘
```

Phase advances each frame. Amplitude modulated by `frame.rms`.
Left and right mirrored for symmetry.

### 4. Scrolling Rainbow

```text
  LEFT           RIGHT
  ┌───┐          ┌───┐
  │ R │ 5        │ R │ 11    continuous hue gradient
  │ O │ 4        │ O │ 10    scroll speed = tempo / beat
  │ Y │ 3        │ Y │  9    brightness pulsed by RMS
  │ G │ 2        │ G │  8    left and right mirrored
  │ B │ 1        │ B │  7
  │ V │ 0        │ V │  6
  └───┘          └───┘
```

Ambient mode. Scroll speed optionally locked to beat tempo.
Brightness = `frame.rms`. Nice fallback when you want color without
intensity-tracking.

### 5. Beat Pulse

```text
  Idle:           On beat:
  ┌───┐           ┌───┐
  │ ░ │           │ █ │      all 12 flash to full on is_beat
  │ ░ │           │ █ │      fast exponential decay (~200ms)
  │ ░ │           │ █ │      color = chroma or freq_to_hue
  │ ░ │           │ █ │
  │ ░ │           │ █ │
  │ ░ │           │ █ │
  └───┘           └───┘
```

Most minimal. Pairs well with complex keyboard effects — side bars
just punctuate the beat.

## File Structure

```text
src/nuphy_rgb/
  side_effects/
    __init__.py          # ALL_SIDE_EFFECTS list
    off.py               # SideOff
    vu_meter.py          # SideVUMeter
    wave.py              # SideWave
    rainbow.py           # SideRainbow
    beat_pulse.py        # SideBeatPulse
```

## Review Findings

### `_HotkeyState` has a latent bug

Adding `side_idx` to the existing `_HotkeyState` creates a conflict:
the single `changed` flag conflates keyboard and side effect switches.
`poll_changed()` returns an index that's ambiguous about which dimension
changed.

**Fix:** Extract a `_CyclicIndex` class (index + changed flag + lock)
and compose two of them:

```python
class _CyclicIndex:
    def __init__(self, count: int): ...
    def next(self) -> None: ...
    def prev(self) -> None: ...
    def poll_changed(self) -> int | None: ...

class _HotkeyState:
    key = _CyclicIndex(count=len(visualizers))
    side = _CyclicIndex(count=len(side_visualizers))
    quit: bool = False
```

This is a prerequisite for implementing side effects — do it first.

### Phase drift between keyboard + side effects

Independent effects processing the same `is_beat` with different
`ExpFilter` alphas will diverge over time. The Wave effect (which has
a phase accumulator) makes this concrete — two phase accumulators
running at slightly different effective rates will drift.

**Decision needed before implementation:** Is `render(frame)` the
permanent plugin contract, or do we add a shared `RenderContext`?

```python
@dataclass
class RenderContext:
    frame: AudioFrame
    beat_phase: float      # 0.0–1.0 within current beat
    frame_number: int      # monotonic shared clock
```

Options:
- **Accept drift** — fine for frame-reactive effects (VU meter, beat
  pulse). Breaks for accumulated-phase effects (wave).
- **Add RenderContext now** — correct, but breaks all 6 existing effects.
- **Add RenderContext later** — easier now, painful retrofit after
  plugins exist.

### Plugin discovery needs explicit markers

Scanning for classes with `name` + `render()` via `importlib` will
produce false positives. Require an explicit marker:

```python
class SideVUMeter:
    __effect_type__ = "side"  # explicit marker for discovery
    name = "VU Meter"
    def render(self, frame: AudioFrame) -> list[tuple[int, int, int]]: ...
```

### HID write latency

Two sequential blocking HID writes per device per frame (keyboard +
side LEDs) doubles HID I/O time. Profile before committing to 30fps
with side LEDs active.

## Open Questions

1. **`render(frame)` vs `render(context)`?** See phase drift section
   above. This is the most consequential decision — it determines the
   plugin contract.

2. **Side effect simulation?** We have an offline sim for keyboard
   effects. Extend it to show a 6-LED strip alongside the keyboard grid.

3. **Naming convention:** `SideVisualizer` (consistent with `Visualizer`)
   vs `SideEffect` (shorter). Note: `SideEffect` is a Python term of art
   in FP — could be confusing. Recommend `SideVisualizer`.

4. **Shared state between key + side effects?** The n×m matrix model
   commits to "accompaniment" (independent). If we ever want "extension"
   (side bars are part of the keyboard effect's design), the protocol
   is wrong. This is a product decision, not a technical one.
