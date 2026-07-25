"""Offline tests for the persistent results store."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from results_store import ResultsStore


def _rows():
    return [
        {"action": "serve", "team": "FRA", "player": "1", "video_timestamp": "10:13",
         "serve_from_lateral": 0.5, "target_depth": 0.7, "target_lateral": 0.2, "target_zone": 5},
        {"action": "serve", "team": "USA", "player": "8", "video_timestamp": "11:10",
         "serve_from_lateral": 0.1, "target_depth": 0.6, "target_lateral": 0.8, "target_zone": 1},
        {"action": "spike", "team": "FRA", "player": "12", "video_timestamp": "11:20"},
    ]


def test_add_run_persists_and_reloads(tmp_path):
    path = str(tmp_path / "db.json")
    ResultsStore(path).add_run(_rows(), source="game.mp4", model="pro")
    reloaded = ResultsStore(path)
    assert len(reloaded.records) == 3
    assert reloaded.records[0]["source"] == "game.mp4"
    assert reloaded.records[0]["run"]  # timestamp tag added


def test_add_run_accumulates(tmp_path):
    path = str(tmp_path / "db.json")
    s = ResultsStore(path)
    s.add_run(_rows())
    s.add_run(_rows())
    assert len(ResultsStore(path).records) == 6


def test_distinct(tmp_path):
    s = ResultsStore(str(tmp_path / "db.json")); s.add_run(_rows())
    assert s.distinct("team") == ["FRA", "USA"]
    assert s.distinct("action") == ["serve", "spike"]


def test_filter_combinations(tmp_path):
    s = ResultsStore(str(tmp_path / "db.json")); s.add_run(_rows())
    assert len(s.filter(team="FRA")) == 2
    assert len(s.filter(team="FRA", action="serve")) == 1
    assert len(s.filter(player="8")) == 1
    assert len(s.filter()) == 3  # no filter = all


def test_clear(tmp_path):
    path = str(tmp_path / "db.json")
    s = ResultsStore(path); s.add_run(_rows()); s.clear()
    assert ResultsStore(path).records == []


def test_serve_placements_only_serves_with_placement(tmp_path):
    s = ResultsStore(str(tmp_path / "db.json")); s.add_run(_rows())
    placements = ResultsStore.serve_placements(s.records)
    assert len(placements) == 2  # spike excluded, both serves have placement
    assert {p["team"] for p in placements} == {"FRA", "USA"}
    assert "target_zone" in placements[0]
