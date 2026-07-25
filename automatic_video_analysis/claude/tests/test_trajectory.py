"""Offline unit tests for the trajectory math + parsing. No network/API needed."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trajectory import TrajPoint, points_from_json, fit_arc, _to_px


# --------------------------- JSON parsing ------------------------------- #
SAMPLE = """[
  {"label":"serve_contact","clip_time":"0:04","y":210,"x":150,"confidence":1.0},
  {"label":"net_crossing","clip_time":"0:05","y":300,"x":500,"confidence":1.0},
  {"label":"reception","clip_time":"0:06","y":650,"x":800,"confidence":0.9}
]"""


def test_points_from_json_basic():
    pts = points_from_json(SAMPLE)
    assert [p.label for p in pts] == ["serve_contact", "net_crossing", "reception"]
    assert pts[0].x == 150 and pts[2].y == 650


def test_points_from_json_fenced_and_wrapped():
    assert len(points_from_json("```json\n" + SAMPLE + "\n```")) == 3
    assert len(points_from_json('{"points": ' + SAMPLE + "}")) == 3


def test_trajpoint_defaults():
    p = TrajPoint(label="reception", y=100, x=200)
    assert p.clip_time == "0:00" and p.confidence == 0.0


# --------------------------- coordinate mapping ------------------------- #
def test_to_px_normalizes_0_1000():
    p = TrajPoint(label="x", y=500, x=250)
    assert _to_px(p, 800, 480) == (200.0, 240.0)  # x=250/1000*800, y=500/1000*480


# --------------------------- arc fitting -------------------------------- #
def test_fit_arc_passes_through_endpoints():
    flight = [(150.0, 100.0), (500.0, 300.0), (800.0, 650.0)]
    arc = fit_arc(flight, samples=50)
    assert arc[0] == (150, 100)      # exact fit through first point
    assert arc[-1] == (800, 650)     # ...and last
    # x increases monotonically across a cross-court serve
    xs = [p[0] for p in arc]
    assert xs == sorted(xs)


def test_fit_arc_handles_vertical_path():
    # near-constant x (serve straight down the middle) must not blow up
    flight = [(490.0, 210.0), (490.0, 300.0), (490.0, 650.0)]
    arc = fit_arc(flight, samples=30)
    assert all(abs(px - 490) <= 1 for px, _ in arc)
    ys = [p[1] for p in arc]
    assert ys[0] < ys[-1]


def test_fit_arc_two_points_is_line():
    arc = fit_arc([(0.0, 0.0), (100.0, 100.0)], samples=11)
    assert arc[0] == (0, 0) and arc[-1] == (100, 100)
    assert arc[5] == (50, 50)  # midpoint of a straight line


def test_fit_arc_single_point_passthrough():
    assert fit_arc([(10.0, 20.0)]) == [(10, 20)]


# --------------------------- top-down court chart ----------------------- #
def test_render_court_chart_writes_png(tmp_path):
    from court_chart import render_court_chart
    serves = [
        {"label": "8", "serve_from_lateral": 0.1, "target_depth": 0.8, "target_lateral": 0.2, "target_zone": 5},
        {"label": "12", "serve_from_lateral": 0.9, "target_depth": 0.6, "target_lateral": 0.7, "target_zone": 1},
    ]
    out = tmp_path / "court.png"
    info = render_court_chart(serves, str(out))
    assert out.exists() and out.stat().st_size > 0
    assert set(info["servers"]) == {"8", "12"} and info["count"] == 2


def test_render_court_chart_tolerates_missing_and_out_of_range(tmp_path):
    from court_chart import render_court_chart
    # missing fields + out-of-range values must not crash (clamped)
    serves = [{"label": "x"}, {"label": "y", "serve_from_lateral": 5, "target_depth": -2, "target_lateral": None}]
    out = tmp_path / "court2.png"
    info = render_court_chart(serves, str(out))
    assert out.exists() and info["count"] == 2


def test_color_by_team_vs_player_groups_differently(tmp_path):
    from court_chart import render_court_chart
    serves = [
        {"team": "FRA", "player": "1", "serve_from_lateral": 0.5, "target_depth": 0.7, "target_lateral": 0.2},
        {"team": "FRA", "player": "9", "serve_from_lateral": 0.4, "target_depth": 0.6, "target_lateral": 0.3},
        {"team": "USA", "player": "8", "serve_from_lateral": 0.1, "target_depth": 0.6, "target_lateral": 0.8},
    ]
    by_team = render_court_chart(serves, str(tmp_path / "t.png"), color_by="team")
    by_player = render_court_chart(serves, str(tmp_path / "p.png"), color_by="player")
    assert set(by_team["servers"]) == {"FRA", "USA"}          # 2 team colors
    assert len(by_player["servers"]) == 3                      # 3 player colors


def test_render_zone_heatmap(tmp_path):
    from court_chart import render_zone_heatmap
    serves = [{"team": "FRA", "target_depth": 0.7, "target_lateral": 0.2, "target_zone": 5}] * 4
    info = render_zone_heatmap([dict(s) for s in serves], str(tmp_path / "h.png"))
    assert (tmp_path / "h.png").exists() and info["count"] == 4


def test_render_zone_heatmap_empty_ok(tmp_path):
    from court_chart import render_zone_heatmap
    info = render_zone_heatmap([], str(tmp_path / "e.png"))
    assert (tmp_path / "e.png").exists() and info["count"] == 0


def test_render_split_by_team(tmp_path):
    from court_chart import render_split_by_team
    serves = [
        {"team": "FRA", "player": "1", "serve_from_lateral": 0.5, "target_depth": 0.7, "target_lateral": 0.2},
        {"team": "USA", "player": "8", "serve_from_lateral": 0.1, "target_depth": 0.6, "target_lateral": 0.8},
    ]
    info = render_split_by_team(serves, str(tmp_path / "s.png"))
    assert (tmp_path / "s.png").exists() and set(info["teams"]) == {"FRA", "USA"}
