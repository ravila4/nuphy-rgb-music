# Interference Pond

Each beat drops a ripple at a random keyboard position. Up to eight ripples
expand simultaneously; their superimposed wave fields produce constructive and
destructive interference patterns mapped to color and brightness per LED.

## Inspiration

Two stones dropped in a pond. Where crests meet, the water piles higher. Where
a crest meets a trough, they cancel. The keyboard grid is the pond surface; the
LEDs sample the instantaneous displacement field.

## Wave Model

Each ripple is a circular wave expanding outward from a source point `(cx, cy)`
in normalized grid coordinates:

```
displacement = amplitude * envelope(dist, radius) * sin(2π(dist - radius) / λ)
```

The `envelope` is a Gaussian centered on the wavefront (`dist ≈ radius`),
widening as the ripple expands to simulate natural dispersion. Bass energy
increases expansion speed and wavelength, so heavy passages produce slower,
chunkier rings.

All active ripples are summed linearly. Superposition is exact: the wave
equation evaluated at each LED position.

## Color

Hue at spawn time comes from the dominant frequency in the current audio frame
(`freq_to_hue`). When multiple ripples overlap, their hues are blended via
circular mean: each ripple contributes a weighted vector on the hue circle, and
`arctan2` of the sum gives the blended angle. This avoids the wrap-around
artifacts of linear hue averaging (e.g., blending hue 0.95 and 0.05 gives 0.0,
not 0.5).

Destructive interference (negative wave sum) flips hue by 180° and reduces
saturation to 0.6, giving cancelled regions a visually distinct complementary
color rather than simply going dark.

High-frequency energy above 0.7 introduces white sparkle: random LEDs
desaturate briefly, simulating sunlight glinting off disturbed water.

## Brightness

An auto-gain stage tracks the rolling peak wave amplitude and normalizes against
it, so the pattern stays readable across quiet and loud passages. A `sqrt`
transform on the normalized wave lifts mid-range LEDs; without it, most of the
grid collapses toward black with only the constructive peaks visible.

Final brightness scales linearly with `raw_rms * brightness_gain`.

## Tunable Parameters

| Parameter        | Default | Range      | Effect                                          |
|-----------------|---------|------------|-------------------------------------------------|
| `brightness_gain`| 5.0     | 1.0–10.0   | RMS -> brightness sensitivity                    |
| `ripple_decay`   | 0.96    | 0.90–0.99  | Amplitude decay per frame (longer-lived ripples)|
| `wavelength`     | 0.15    | 0.08–0.30  | Base ring spacing (lower = finer bands)         |
