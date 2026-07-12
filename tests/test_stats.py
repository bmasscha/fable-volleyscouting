"""Tests for core.stats: compute_stats, export_csv, export_html."""
import csv

import pytest

from core.events import (
    AttackEvent,
    DigEvent,
    ManualScoreEvent,
    RallyPointEvent,
    ReceptionEvent,
    ServeEvent,
)
from core.models import HOME, AWAY, Player, Rating, Role, Skill, Team
from core.stats import (
    ACES,
    KILLS,
    MANUAL_OTHER,
    OPPONENT_ERRORS,
    SkillLine,
    compute_stats,
    export_csv,
    export_html,
)


@pytest.fixture
def teams():
    alice = Player(number=1, name="Alice", role=Role.OUTSIDE, id="p_alice")
    bob = Player(number=9, name="Bob", role=Role.OPPOSITE, id="p_bob")
    carol = Player(number=7, name="Carol", role=Role.LIBERO, id="p_carol")
    return {
        HOME: Team("Home Hawks", players=[alice, bob]),
        AWAY: Team("Away Owls", players=[carol]),
    }


@pytest.fixture
def events():
    return [
        # Alice serves: one ace, one error, one good.
        ServeEvent(team=HOME, player_id="p_alice", rating=Rating.PERFECT),
        ServeEvent(team=HOME, player_id="p_alice", rating=Rating.ERROR),
        ServeEvent(team=HOME, player_id="p_alice", rating=Rating.GOOD),
        # Bob attacks: one kill, one poor.
        AttackEvent(team=HOME, player_id="p_bob", rating=Rating.PERFECT),
        AttackEvent(team=HOME, player_id="p_bob", rating=Rating.POOR),
        # Carol (away): reception error (-> home point), a good dig.
        ReceptionEvent(team=AWAY, player_id="p_carol", rating=Rating.ERROR),
        DigEvent(team=AWAY, player_id="p_carol", rating=Rating.GOOD),
        # Manual events.
        RallyPointEvent(team=HOME, reason="net fault"),
        ManualScoreEvent(team=AWAY, delta=2),
        ManualScoreEvent(team=AWAY, delta=-1),
        # Unknown player: must be skipped gracefully.
        ServeEvent(team=HOME, player_id="p_ghost", rating=Rating.PERFECT),
    ]


@pytest.fixture
def stats(events, teams):
    return compute_stats(events, teams)


# ------------------------------------------------------------- SkillLine

def test_skill_line_empty_is_all_zero():
    line = SkillLine()
    assert line.total == 0
    assert line.pct(Rating.PERFECT) == 0.0
    assert line.efficiency == 0.0
    assert line.positive_pct == 0.0


def test_skill_line_math():
    line = SkillLine()
    for r in (Rating.PERFECT, Rating.PERFECT, Rating.ERROR, Rating.GOOD):
        line.add(r)
    assert line.total == 4
    assert line.pct(Rating.PERFECT) == pytest.approx(50.0)
    assert line.efficiency == pytest.approx((2 - 1) / 4 * 100)
    assert line.positive_pct == pytest.approx((2 + 1) / 4 * 100)


# ---------------------------------------------------------- compute_stats

def test_player_serve_counts(stats):
    serve = stats[HOME].players["p_alice"].line(Skill.SERVE)
    assert serve.total == 3
    assert serve.count(Rating.PERFECT) == 1
    assert serve.count(Rating.ERROR) == 1
    assert serve.count(Rating.GOOD) == 1
    assert serve.count(Rating.POOR) == 0
    assert serve.pct(Rating.PERFECT) == pytest.approx(100 / 3)
    assert serve.efficiency == pytest.approx(0.0)
    assert serve.positive_pct == pytest.approx(200 / 3)


def test_player_points(stats):
    assert stats[HOME].players["p_alice"].points == 1  # one ace
    assert stats[HOME].players["p_bob"].points == 1    # one kill
    assert stats[AWAY].players["p_carol"].points == 0


def test_team_totals_skip_unknown_player(stats):
    # The p_ghost ace must not be counted anywhere.
    assert stats[HOME].totals[Skill.SERVE].total == 3
    assert stats[HOME].totals[Skill.SERVE].count(Rating.PERFECT) == 1
    assert stats[HOME].totals[Skill.ATTACK].total == 2
    assert stats[AWAY].totals[Skill.RECEPTION].total == 1
    assert stats[AWAY].totals[Skill.DIG].count(Rating.GOOD) == 1


def test_points_breakdown_home(stats):
    bd = stats[HOME].points_breakdown
    assert bd[ACES] == 1
    assert bd[KILLS] == 1
    assert bd[OPPONENT_ERRORS] == 1     # Carol's reception error
    assert bd[MANUAL_OTHER] == 1        # one rally point, no score deltas
    assert stats[HOME].total_points == 4


def test_points_breakdown_away(stats):
    bd = stats[AWAY].points_breakdown
    assert bd[ACES] == 0
    assert bd[KILLS] == 0
    assert bd[OPPONENT_ERRORS] == 1     # Alice's serve error
    assert bd[MANUAL_OTHER] == 1        # net manual delta +2 - 1
    assert stats[AWAY].total_points == 2


def test_no_events_gives_zeroed_stats(teams):
    stats = compute_stats([], teams)
    assert stats[HOME].total_points == 0
    assert stats[HOME].players["p_alice"].points == 0
    assert stats[AWAY].totals[Skill.DIG].total == 0


# -------------------------------------------------------------- export_csv

def test_export_csv(stats, teams, tmp_path):
    path = tmp_path / "stats.csv"
    export_csv(stats, teams, str(path))
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    header = rows[0]
    assert header[:4] == ["team", "number", "name", "role"]
    assert "serve_total" in header
    assert "dig_eff_pct" in header
    assert header[-1] == "points"
    # 3 players + 2 team-total rows.
    assert len(rows) == 1 + 5

    alice = rows[1]
    assert alice[:4] == ["Home Hawks", "1", "Alice", "outside"]
    i = header.index("serve_total")
    assert alice[i:i + 6] == ["3", "1", "0", "1", "1", "0.0"]
    assert alice[-1] == "1"

    home_total = rows[3]
    assert home_total[2] == "TEAM TOTAL"
    assert home_total[i] == "3"
    j = header.index("attack_total")
    assert home_total[j:j + 6] == ["2", "0", "1", "0", "1", "50.0"]
    assert home_total[-1] == "4"

    away_total = rows[5]
    assert away_total[0] == "Away Owls"
    assert away_total[-1] == "2"


# ------------------------------------------------------------- export_html

def test_export_html(stats, teams, tmp_path):
    path = tmp_path / "report.html"
    export_html(stats, teams, str(path))
    text = path.read_text(encoding="utf-8")

    assert text.lstrip().startswith("<!DOCTYPE html>")
    for name in ("Alice", "Bob", "Carol", "Home Hawks", "Away Owls"):
        assert name in text
    assert "TEAM TOTAL" in text
    assert "aces 1" in text          # home breakdown
    assert "opponent errors 1" in text
    assert "manual/other 1" in text


def test_export_html_escapes_names(teams, tmp_path):
    teams[HOME].players[0].name = "A<script>lice"
    stats = compute_stats([], teams)
    path = tmp_path / "report.html"
    export_html(stats, teams, str(path))
    text = path.read_text(encoding="utf-8")
    assert "<script>" not in text
    assert "A&lt;script&gt;lice" in text
