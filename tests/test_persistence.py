"""Round-trip tests for core.persistence: match save/load, event
(de)serialization symmetry for every event type, atomic writes, and the
roster library."""
import json

import pytest

from core import persistence
from core.events import (AttackEvent, DigEvent, LiberoSwapEvent,
                         ManualScoreEvent, RallyPointEvent, ReceptionEvent,
                         ServeEvent, ServeOverrideEvent, SetStartEvent,
                         SubstitutionEvent, TimeoutEvent, event_from_dict,
                         event_to_dict)
from core.models import AWAY, HOME, MatchConfig, Player, Rating, Role, Team


def make_teams():
    home = Team(name="Home", color="#123456",
                players=[Player(number=i + 1, name=f"H{i + 1}",
                                role=Role.SETTER if i == 0 else
                                Role.LIBERO if i == 6 else Role.OUTSIDE)
                         for i in range(9)])
    away = Team(name="Away", color="#654321",
                players=[Player(number=i + 51, name=f"A{i + 1}")
                         for i in range(9)])
    return {HOME: home, AWAY: away}


def all_event_samples(teams):
    h = [p.id for p in teams[HOME].players]
    a = [p.id for p in teams[AWAY].players]
    return [
        SetStartEvent(set_number=1, lineups={HOME: h[:6], AWAY: a[:6]},
                      liberos={HOME: [h[6]], AWAY: [a[6]]},
                      serving_team=HOME, left_team=AWAY),
        ServeEvent(team=HOME, player_id=h[0], rating=Rating.GOOD,
                   trajectory=(-10.2, 7.5, 4.4, 3.1)),
        ServeEvent(team=HOME, player_id=h[0], rating=Rating.ERROR),
        ReceptionEvent(team=AWAY, player_id=a[4], rating=Rating.PERFECT),
        AttackEvent(team=AWAY, player_id=a[1], rating=Rating.POOR,
                    trajectory=(2.0, 1.0, -6.0, 8.0)),
        AttackEvent(team=AWAY, player_id=a[1], rating=Rating.PERFECT),
        DigEvent(team=HOME, player_id=h[5], rating=Rating.GOOD),
        RallyPointEvent(team=AWAY, reason="net fault"),
        SubstitutionEvent(team=HOME, player_out=h[0], player_in=h[7]),
        LiberoSwapEvent(team=AWAY, libero_id=a[6], partner_id=a[2]),
        ManualScoreEvent(team=HOME, delta=-1),
        ServeOverrideEvent(team=AWAY),
        TimeoutEvent(team=HOME),
    ]


class TestEventSerialization:
    def test_every_event_type_round_trips(self):
        for e in all_event_samples(make_teams()):
            assert event_from_dict(event_to_dict(e)) == e

    def test_rating_serialized_as_symbol(self):
        teams = make_teams()
        e = ServeEvent(team=HOME, player_id=teams[HOME].players[0].id,
                       rating=Rating.PERFECT)
        assert event_to_dict(e)["rating"] == "#"

    def test_trajectory_list_in_dict_tuple_after_load(self):
        teams = make_teams()
        e = AttackEvent(team=HOME, player_id=teams[HOME].players[0].id,
                        rating=Rating.GOOD, trajectory=(1.0, 2.0, 3.0, 4.0))
        d = event_to_dict(e)
        assert d["trajectory"] == [1.0, 2.0, 3.0, 4.0]
        assert event_from_dict(d).trajectory == (1.0, 2.0, 3.0, 4.0)


class TestMatchRoundTrip:
    def test_full_round_trip(self, tmp_path):
        teams = make_teams()
        config = MatchConfig(sets_to_win=2, points_per_set=21,
                             libero_may_serve=True)
        events = all_event_samples(teams)
        path = tmp_path / "match.json"
        persistence.save_match(path, config, teams, events)

        config2, teams2, events2 = persistence.load_match(path)
        assert config2 == config
        assert events2 == events
        for tk in (HOME, AWAY):
            assert teams2[tk].name == teams[tk].name
            assert teams2[tk].color == teams[tk].color
            assert [(p.id, p.number, p.name, p.role)
                    for p in teams2[tk].players] == \
                   [(p.id, p.number, p.name, p.role)
                    for p in teams[tk].players]

    def test_file_is_valid_json_and_overwrites(self, tmp_path):
        teams = make_teams()
        path = tmp_path / "m.json"
        persistence.save_match(path, MatchConfig(), teams, [])
        assert json.loads(path.read_text(encoding="utf-8"))["events"] == []
        events = all_event_samples(teams)
        persistence.save_match(path, MatchConfig(), teams, events)
        assert len(json.loads(path.read_text(
            encoding="utf-8"))["events"]) == len(events)
        leftovers = [p for p in path.parent.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []


class TestRosterLibrary:
    def test_save_load_delete(self, tmp_path):
        teams = make_teams()
        persistence.save_team(teams[HOME], base=tmp_path)
        persistence.save_team(teams[AWAY], base=tmp_path)
        loaded = persistence.load_teams(base=tmp_path)
        assert sorted(t.name for t in loaded) == ["Away", "Home"]
        home2 = next(t for t in loaded if t.name == "Home")
        assert home2.players[6].role == Role.LIBERO
        persistence.delete_team(teams[HOME], base=tmp_path)
        assert [t.name for t in
                persistence.load_teams(base=tmp_path)] == ["Away"]

    def test_name_sanitization(self, tmp_path):
        weird = Team(name="A/B: C?", players=[Player(number=1, name="X")])
        path = persistence.save_team(weird, base=tmp_path)
        assert path.exists()
        loaded = persistence.load_teams(base=tmp_path)
        assert loaded[0].name == "A/B: C?"   # name survives inside the JSON

    def test_corrupt_file_skipped(self, tmp_path):
        (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
        persistence.save_team(Team(name="OK"), base=tmp_path)
        assert [t.name for t in persistence.load_teams(base=tmp_path)] == ["OK"]
