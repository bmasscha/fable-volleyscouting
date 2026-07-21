"""Pure-logic unit tests for ui/token_colors.py (no Qt required)."""
from ui.token_colors import (
    LIBERO_PALETTE,
    _redmean_distance,
    ink_for,
    libero_color_for,
    outline_for,
)


def test_ink_for_dark_on_light():
    assert ink_for("#ffffff") == "#000000"   # white jersey -> black ink
    assert ink_for("#fbc02d") == "#000000"   # yellow jersey -> black ink


def test_ink_for_light_on_dark():
    assert ink_for("#000000") == "#ffffff"   # black jersey -> white ink
    assert ink_for("#0d1b3e") == "#ffffff"   # navy jersey -> white ink


def test_outline_is_opposite_of_ink():
    assert outline_for("#000000") == "#ffffff"
    assert outline_for("#ffffff") == "#000000"


def test_libero_for_red_team_is_not_reddish():
    team = "#d32f2f"                          # red team
    result = libero_color_for(team)
    assert result != team                     # never the team colour
    assert result != "#d32f2f"                # never the red palette entry
    # picked colour must be clearly distinct from red
    assert _redmean_distance(result, team) > _redmean_distance("#d32f2f", team)


def test_libero_for_white_is_near_black():
    assert libero_color_for("#ffffff") == "#212121"


def test_libero_for_black_is_white():
    assert libero_color_for("#000000") == "#ffffff"


def test_libero_output_always_in_palette():
    for team in ("#d32f2f", "#ffffff", "#000000", "#2e7d32",
                 "#1565c0", "#e8853b", "#8e24aa"):
        assert libero_color_for(team) in LIBERO_PALETTE


def test_libero_is_deterministic():
    for team in ("#d32f2f", "#123456", "#abcdef"):
        assert libero_color_for(team) == libero_color_for(team)
