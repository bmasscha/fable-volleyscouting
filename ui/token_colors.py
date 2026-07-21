"""Derived colours for player tokens, so the jersey colour (the user's free
choice) never makes the number, badge or border unreadable, and the libero's
mandatory contrasting jersey never clashes with the team colour.

The desktop app (ui/player_token.py, ui/bench_panel.py) and the tablet
(tablet/src/tokenColors.ts) MUST derive identical colours from the same input,
so keep the two files in lock-step: same palette, same order, same maths.
"""
from __future__ import annotations

BLACK = "#000000"
WHITE = "#ffffff"

# Curated jersey colours a libero might realistically wear. Deliberately EXCLUDES
# orange -- the court itself is orange (#e8853b), so an orange libero would blend
# into the floor. Order is significant: it breaks ties deterministically.
LIBERO_PALETTE = (
    "#d32f2f",  # red
    "#fbc02d",  # yellow
    "#7cb342",  # lime
    "#00acc1",  # teal
    "#1e88e5",  # blue
    "#8e24aa",  # purple
    "#d81b60",  # magenta
    "#ffffff",  # white
    "#212121",  # near-black
)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse '#rgb' or '#rrggbb' (any case) into 0-255 ints."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _relative_luminance(hex_color: str) -> float:
    """WCAG 2.x relative luminance of a colour, in [0, 1]."""
    def chan(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hex_color)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def ink_for(fill: str) -> str:
    """Black or white -- whichever has the higher WCAG contrast against `fill`.
    Use for the number, badge and disc border drawn on a coloured token."""
    lum = _relative_luminance(fill)
    contrast_white = (1.0 + 0.05) / (lum + 0.05)
    contrast_black = (lum + 0.05) / 0.05
    return BLACK if contrast_black >= contrast_white else WHITE


def outline_for(ink: str) -> str:
    """The opposite of the ink colour -- a thin halo behind the glyph so the
    number stays crisp on muddy mid-tone jerseys where neither ink is ideal."""
    return WHITE if ink == BLACK else BLACK


def _redmean_distance(a: str, b: str) -> float:
    """Low-cost perceptual colour distance ('redmean'). Larger == more distinct."""
    r1, g1, b1 = _rgb(a)
    r2, g2, b2 = _rgb(b)
    rmean = (r1 + r2) / 2.0
    dr, dg, db = r1 - r2, g1 - g2, b1 - b2
    return (
        (2 + rmean / 256) * dr * dr
        + 4 * dg * dg
        + (2 + (255 - rmean) / 256) * db * db
    ) ** 0.5


def libero_color_for(team_color: str) -> str:
    """Pick the palette colour most perceptually distinct from the team colour,
    so a red team never gets a red libero. Deterministic (ties -> palette order)."""
    best = LIBERO_PALETTE[0]
    best_dist = -1.0
    for candidate in LIBERO_PALETTE:
        dist = _redmean_distance(candidate, team_color)
        if dist > best_dist:
            best, best_dist = candidate, dist
    return best
