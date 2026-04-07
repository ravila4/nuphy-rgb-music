"""Spatial mapping for the NuPhy Air75 V2 keyboard LED grid.

All visualizers that need spatial awareness import from here.
LED indices alternate direction per row (odd rows reversed).
"""

import numpy as np

NUM_LEDS = 84
NUM_ROWS = 6
MAX_COLS = 16

# Each entry: list of LED indices, left-to-right as physically laid out
ROWS: list[list[int]] = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],       # 16 keys
    [30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16],   # 15 keys
    [31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45],   # 15 keys
    [59, 58, 57, 56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46],       # 14 keys
    [60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73],       # 14 keys
    [83, 82, 81, 80, 79, 78, 77, 76, 75, 74],                        # 10 keys
]

# LED index -> (row, col) in physical grid
LED_ROW_COL: list[tuple[int, int]] = [(0, 0)] * NUM_LEDS
for _row_idx, _leds in enumerate(ROWS):
    for _col_idx, _led_idx in enumerate(_leds):
        LED_ROW_COL[_led_idx] = (_row_idx, _col_idx)

# LED index -> normalized (x, y) in [0, 1] range
LED_XY: list[tuple[float, float]] = [
    (col / (MAX_COLS - 1), row / (NUM_ROWS - 1))
    for row, col in LED_ROW_COL
]

# (row, col) -> LED index (-1 if no key at that position)
RC_TO_LED: dict[tuple[int, int], int] = {}
for _led_idx, (_r, _c) in enumerate(LED_ROW_COL):
    RC_TO_LED[(_r, _c)] = _led_idx

# Adjacency map: (row, col) -> list of neighboring (row, col)
# Includes cardinal + diagonal neighbors that exist on the grid
NEIGHBORS: dict[tuple[int, int], list[tuple[int, int]]] = {}
for _rc in RC_TO_LED:
    _r, _c = _rc
    _nbrs = []
    for _dr, _dc in [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]:
        _nr, _nc = _r + _dr, _c + _dc
        if (_nr, _nc) in RC_TO_LED:
            _nbrs.append((_nr, _nc))
    NEIGHBORS[_rc] = _nbrs

# Numpy arrays for vectorized distance calculations
LED_X = np.array([xy[0] for xy in LED_XY], dtype=np.float64)
LED_Y = np.array([xy[1] for xy in LED_XY], dtype=np.float64)

# Grid-shaped arrays for effects that operate on the 2D grid
Y_GRID, X_GRID = np.mgrid[0:NUM_ROWS, 0:MAX_COLS].astype(np.float32)
VALID_MASK = np.zeros((NUM_ROWS, MAX_COLS), dtype=bool)
for _row_idx, _leds in enumerate(ROWS):
    for _col_idx in range(len(_leds)):
        VALID_MASK[_row_idx, _col_idx] = True
VALID_FLOAT = VALID_MASK.astype(np.float32)


def blur3(field: np.ndarray) -> np.ndarray:
    """3x3 box blur on a 2D array. Zero-padded edges."""
    p = np.pad(field, ((1, 1), (1, 1)), mode="constant")
    return (
        p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:]
        + p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:]
        + p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]
    ) / 9.0


def gradient_mag(field: np.ndarray) -> np.ndarray:
    """Gradient magnitude via central differences. Edge-padded."""
    p = np.pad(field, ((1, 1), (1, 1)), mode="edge")
    dx = (p[1:-1, 2:] - p[1:-1, :-2]) * 0.5
    dy = (p[2:, 1:-1] - p[:-2, 1:-1]) * 0.5
    return np.sqrt(dx * dx + dy * dy)


def grid_to_leds(rgb_grid: np.ndarray) -> list[tuple[int, int, int]]:
    """Convert a (NUM_ROWS, MAX_COLS, 3) float grid [0-1] to 84 RGB tuples."""
    rgb_grid = np.clip(rgb_grid * VALID_FLOAT[..., None], 0.0, 1.0)
    out: list[tuple[int, int, int]] = [(0, 0, 0)] * NUM_LEDS
    for led in range(NUM_LEDS):
        r, c = LED_ROW_COL[led]
        out[led] = (
            int(rgb_grid[r, c, 0] * 255 + 0.5),
            int(rgb_grid[r, c, 1] * 255 + 0.5),
            int(rgb_grid[r, c, 2] * 255 + 0.5),
        )
    return out
