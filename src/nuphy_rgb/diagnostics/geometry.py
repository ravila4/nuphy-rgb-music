"""Physical key geometry for the NuPhy Air75 V2.

Per-key (x, width) in keyboard units ("u", 1u = one standard keycap),
indexed by logical (grid_row, grid_col) as used in ``effects.grid``.

Only consumed by visualization diagnostics — effects themselves work in
logical row/col coordinates and don't care about physical key widths.
If that ever changes, this module can be promoted out of ``diagnostics``.

Grid rows and their key counts match ``effects.grid.ROWS``:
    row 0: 16 keys (Esc/F-row/Ins/Del)
    row 1: 15 keys (number row, wide Backspace at col 13, PgUp at col 14)
    row 2: 15 keys (1.5u Tab, QWERTY, 1.5u \\, PgDn)
    row 3: 14 keys (1.75u Caps, ASDF, 2.25u Enter, Home)
    row 4: 14 keys (2.25u LShift, ZXCV, 1.75u RShift, Up, End)
    row 5: 10 keys (1.25u mods, 6.25u Space, mods, arrow cluster)

Derived from ``qmk-firmware/keyboards/nuphy/air75v2/ansi/keyboard.json``.
"""

from __future__ import annotations

from dataclasses import dataclass

from nuphy_rgb.effects.grid import NUM_LEDS, ROWS

# (x_u, width_u) per logical column, per logical row.
# Row index matches ROWS in effects.grid; column index is position within that row.
KEY_XW: list[list[tuple[float, float]]] = [
    # row 0 — Esc F1..F12 Print Ins Del
    [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1),
     (8, 1), (9, 1), (10, 1), (11, 1), (12, 1), (13, 1), (14, 1), (15, 1)],
    # row 1 — ` 1..0 - = Backspace(2u) PgUp
    [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1),
     (8, 1), (9, 1), (10, 1), (11, 1), (12, 1), (13, 2), (15, 1)],
    # row 2 — Tab(1.5u) QWERTYUIOP [ ] \(1.5u) PgDn
    [(0, 1.5), (1.5, 1), (2.5, 1), (3.5, 1), (4.5, 1), (5.5, 1), (6.5, 1),
     (7.5, 1), (8.5, 1), (9.5, 1), (10.5, 1), (11.5, 1), (12.5, 1),
     (13.5, 1.5), (15, 1)],
    # row 3 — Caps(1.75u) ASDFGHJKL ; ' Enter(2.25u) Home
    [(0, 1.75), (1.75, 1), (2.75, 1), (3.75, 1), (4.75, 1), (5.75, 1),
     (6.75, 1), (7.75, 1), (8.75, 1), (9.75, 1), (10.75, 1), (11.75, 1),
     (12.75, 2.25), (15, 1)],
    # row 4 — LShift(2.25u) ZXCVBNM , . / RShift(1.75u) Up End
    [(0, 2.25), (2.25, 1), (3.25, 1), (4.25, 1), (5.25, 1), (6.25, 1),
     (7.25, 1), (8.25, 1), (9.25, 1), (10.25, 1), (11.25, 1), (12.25, 1.75),
     (14, 1), (15, 1)],
    # row 5 — Ctrl(1.25u) Opt(1.25u) Cmd(1.25u) Space(6.25u) Cmd Fn Ctrl ← ↓ →
    [(0, 1.25), (1.25, 1.25), (2.5, 1.25), (3.75, 6.25),
     (10, 1), (11, 1), (12, 1), (13, 1), (14, 1), (15, 1)],
]

ROW_Y: list[float] = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]

BOARD_W_U: float = 16.0
BOARD_H_U: float = 6.0


@dataclass(frozen=True)
class KeyRect:
    led: int
    row: int  # logical row (matches effects.grid)
    col: int  # logical col within that row
    x_u: float
    y_u: float
    w_u: float
    h_u: float = 1.0

    @property
    def cx(self) -> float:
        return self.x_u + self.w_u / 2

    @property
    def cy(self) -> float:
        return self.y_u + self.h_u / 2


def _build_key_rects() -> list[KeyRect]:
    rects: list[KeyRect | None] = [None] * NUM_LEDS
    for row_idx, row_leds in enumerate(ROWS):
        xws = KEY_XW[row_idx]
        assert len(xws) == len(row_leds), (
            f"layout row {row_idx} has {len(xws)} keys, grid row has {len(row_leds)}"
        )
        y = ROW_Y[row_idx]
        for col_idx, led in enumerate(row_leds):
            x_u, w_u = xws[col_idx]
            rects[led] = KeyRect(
                led=led, row=row_idx, col=col_idx,
                x_u=x_u, y_u=y, w_u=w_u,
            )
    assert all(r is not None for r in rects)
    return rects  # type: ignore[return-value]


KEY_RECTS: list[KeyRect] = _build_key_rects()
"""One KeyRect per LED index, in LED index order."""


def rect_for_led(led: int) -> KeyRect:
    return KEY_RECTS[led]


def rect_for_grid(row: int, col: int) -> KeyRect:
    led = ROWS[row][col]
    return KEY_RECTS[led]


assert len(KEY_RECTS) == NUM_LEDS
