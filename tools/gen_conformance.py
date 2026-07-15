"""Generate golden conformance fixtures for the tablet TypeScript port.

The Python engine is the reference implementation.  This script replays
scripted and seeded-random matches through core.engine.MatchEngine and
records, for every event: the serialized event, the warnings returned by
append(), and a full state snapshot afterwards -- plus final statistics
(core.stats) and normalized trajectories (core.trajectories).

The TypeScript engine in tablet/src/core must reproduce every fixture
exactly (tablet/tests/conformance.test.ts).  Regenerate with:

    .venv\\Scripts\\python.exe tools\\gen_conformance.py

Run this after every release-relevant change to core/ and re-run the
tablet suite; this is the sync contract described in tablet/RELEASING.md.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from core.blocks import (BLOCK_OUT, COVERED,                     # noqa: E402
                         classify_block_deflection)
from core.engine import MatchEngine, Phase                       # noqa: E402
from core.events import (AttackEvent, DigEvent, LiberoSwapEvent,  # noqa: E402
                         ManualScoreEvent, RallyPointEvent,
                         ReceptionEvent, RotationAdjustEvent, ServeEvent,
                         ServeOverrideEvent, SetStartEvent,
                         SubstitutionEvent, TimeoutEvent, event_to_dict)
from core.models import (AWAY, HOME, MatchConfig, Player, Rating,  # noqa: E402
                         Role, Team, other)
from core.stats import compute_stats                              # noqa: E402
from core.trajectories import collect_trajectories                # noqa: E402

OUT_DIR = REPO / "tablet" / "conformance"


# --------------------------------------------------------------------- teams

def build_team(prefix: str, name: str, color: str) -> Team:
    """12 players with deterministic ids '<prefix>1'..'<prefix>12'.
    Players 1-6 start, 7-11 are bench, 12 is the libero."""
    roles = [Role.SETTER, Role.OUTSIDE, Role.MIDDLE, Role.OUTSIDE,
             Role.MIDDLE, Role.OPPOSITE,
             Role.UNIVERSAL, Role.UNIVERSAL, Role.UNIVERSAL,
             Role.UNIVERSAL, Role.UNIVERSAL, Role.LIBERO]
    players = [Player(number=i + 1, name=f"{prefix}{i + 1}", role=roles[i],
                      id=f"{prefix}{i + 1}")
               for i in range(12)]
    return Team(name=name, players=players, color=color)


def build_teams() -> dict:
    return {HOME: build_team("H", "Home Hawks", "#2e7d32"),
            AWAY: build_team("A", "Away Owls", "#c62828")}


def starters(teams: dict, tk: str) -> list[str]:
    return [p.id for p in teams[tk].players[:6]]


def libero_of(teams: dict, tk: str) -> str:
    return teams[tk].players[11].id


def first_set_start(teams: dict, serving=HOME, left=HOME) -> SetStartEvent:
    return SetStartEvent(
        set_number=1,
        lineups={tk: starters(teams, tk) for tk in (HOME, AWAY)},
        liberos={tk: [libero_of(teams, tk)] for tk in (HOME, AWAY)},
        serving_team=serving, left_team=left)


# ----------------------------------------------------------------- snapshots

def snapshot(engine: MatchEngine) -> dict:
    st = engine.state
    team = {}
    for tk in (HOME, AWAY):
        ts = st.team[tk]
        team[tk] = {
            "lineup": list(ts.lineup),
            "starting_lineup": list(ts.starting_lineup),
            "liberos": list(ts.liberos),
            "subs_used": ts.subs_used,
            "sub_pairs": [list(p) for p in ts.sub_pairs],
            "libero_replaced": dict(ts.libero_replaced),
            "libero_partners": {lib: list(ps)
                                for lib, ps in ts.libero_partners.items()},
            "timeouts": ts.timeouts,
        }
    sug = engine.suggest_next_set_start()
    nxt = engine.next_auto_libero_swap()
    return {
        "phase": st.phase.value,
        "set_number": st.set_number,
        "scores": dict(st.scores),
        "set_scores": dict(st.set_scores),
        "serving_team": st.serving_team,
        "set_first_server": st.set_first_server,
        "left_team": st.left_team,
        "switched_mid_set": st.switched_mid_set,
        "attacking_team": st.attacking_team,
        "last_set_winner": st.last_set_winner,
        "team": team,
        "expected_server": engine.expected_server(),
        "rally_live": engine.rally_live(),
        "set_point_info": engine.set_point_info(),
        "pending_alerts": engine.pending_alerts(),
        "suggest_next": event_to_dict(sug) if sug is not None else None,
        "next_auto_libero_swap": event_to_dict(nxt) if nxt is not None else None,
    }


def stats_to_dict(stats: dict) -> dict:
    out = {}
    for tk, ts in stats.items():
        out[tk] = {
            "players": {
                pid: {sk.value: {r.value: line.count(r) for r in Rating}
                      for sk, line in ps.skills.items()}
                for pid, ps in ts.players.items()},
            "totals": {sk.value: {r.value: line.count(r) for r in Rating}
                       for sk, line in ts.totals.items()},
            "points_breakdown": dict(ts.points_breakdown),
        }
    return out


def trajectories_to_list(trajs: list) -> list:
    return [{"team": t.team, "player_id": t.player_id,
             "skill": t.skill.value, "rating": t.rating.value,
             "set_number": t.set_number, "line": list(t.line),
             "block_touch": (list(t.block_touch)
                             if t.block_touch is not None else None)}
            for t in trajs]


def run_fixture(name: str, config: MatchConfig, teams: dict,
                events: list) -> dict:
    engine = MatchEngine(config, teams)
    steps = []
    for e in events:
        warnings = engine.append(e)
        steps.append({"event": event_to_dict(e), "warnings": warnings,
                      "state": snapshot(engine)})
    return {
        "name": name,
        "config": config.to_dict(),
        "teams": {k: t.to_dict() for k, t in teams.items()},
        "steps": steps,
        "final_stats": stats_to_dict(compute_stats(engine.events, teams)),
        "final_trajectories": trajectories_to_list(
            collect_trajectories(config, teams, engine.events)),
    }


# ------------------------------------------------------------ random matches

def drain_auto_swaps(engine: MatchEngine, events: list) -> None:
    """Mirror of the UI behavior with config.auto_libero: after every
    user event the app appends the engine-proposed libero exchanges."""
    for _ in range(6):
        auto = engine.next_auto_libero_swap()
        if auto is None:
            break
        engine.append(auto)
        events.append(auto)


RATING_CHOICES = [Rating.PERFECT, Rating.ERROR, Rating.GOOD, Rating.POOR]
RATING_WEIGHTS = [8, 8, 60, 24]


def pick_rating(rng: random.Random) -> Rating:
    return rng.choices(RATING_CHOICES, RATING_WEIGHTS)[0]


def rand_traj(rng: random.Random):
    return (round(rng.uniform(-12, 12), 2), round(rng.uniform(-2, 11), 2),
            round(rng.uniform(-12, 12), 2), round(rng.uniform(-2, 11), 2))


# rating a two-segment (blocked) attack gets from where the deflection lands,
# mirroring the auto-finalize rule in both UIs
BLOCK_RATINGS = {BLOCK_OUT: Rating.PERFECT, COVERED: Rating.POOR}


def rand_blocked_attack(rng: random.Random, engine: MatchEngine,
                        tk: str, pid: str) -> AttackEvent:
    traj = rand_traj(rng)
    touch = (round(rng.uniform(-0.8, 0.8), 2), round(rng.uniform(0, 9), 2))
    kind = classify_block_deflection(engine.side_of(tk), traj[2], traj[3])
    return AttackEvent(team=tk, player_id=pid,
                       rating=BLOCK_RATINGS.get(kind, Rating.GOOD),
                       trajectory=traj, block_touch=touch)


def random_match(seed: int, config: MatchConfig,
                 max_events: int = 600) -> tuple[dict, list]:
    """Phase-aware random match: mostly legal play, sprinkled with manual
    corrections and deliberately illegal events to exercise every warning."""
    rng = random.Random(seed)
    teams = build_teams()
    engine = MatchEngine(config, teams)
    events: list = []

    def emit(e) -> None:
        engine.append(e)
        events.append(e)
        drain_auto_swaps(engine, events)

    while len(events) < max_events and engine.state.phase != Phase.MATCH_OVER:
        st = engine.state
        ph = st.phase

        if ph in (Phase.BEFORE_SET, Phase.SET_OVER):
            if ph == Phase.BEFORE_SET:
                emit(first_set_start(teams, serving=rng.choice((HOME, AWAY)),
                                     left=rng.choice((HOME, AWAY))))
            else:
                emit(engine.suggest_next_set_start())
            if rng.random() < 0.4:      # coach picks another start rotation
                emit(RotationAdjustEvent(team=rng.choice((HOME, AWAY)),
                                         steps=rng.randrange(-3, 7)))
            continue

        if ph == Phase.AWAIT_SERVE:
            r = rng.random()
            if r < 0.05:
                emit(TimeoutEvent(team=rng.choice((HOME, AWAY))))
            elif r < 0.11:
                tk = rng.choice((HOME, AWAY))
                ts = st.team[tk]
                bench = [p.id for p in teams[tk].players
                         if p.id not in ts.lineup and p.id not in ts.liberos]
                if bench:
                    pout = (ts.lineup[rng.randrange(6)]
                            if rng.random() < 0.9 else rng.choice(bench))
                    emit(SubstitutionEvent(team=tk, player_out=pout,
                                           player_in=rng.choice(bench)))
            elif r < 0.17:
                tk = rng.choice((HOME, AWAY))
                ts = st.team[tk]
                lib = libero_of(teams, tk)
                if lib in ts.lineup:            # exit (sometimes wrong partner)
                    partner = (ts.libero_replaced.get(lib)
                               if rng.random() < 0.9 else
                               rng.choice(ts.lineup))
                    emit(LiberoSwapEvent(team=tk, libero_id=lib,
                                         partner_id=partner or ts.lineup[0]))
                else:                           # enter (sometimes front row)
                    slot = (rng.choice((0, 4, 5)) if rng.random() < 0.85
                            else rng.randrange(6))
                    emit(LiberoSwapEvent(team=tk, libero_id=lib,
                                         partner_id=ts.lineup[slot]))
            elif r < 0.20:
                emit(ManualScoreEvent(team=rng.choice((HOME, AWAY)),
                                      delta=rng.choice((-1, 1))))
            elif r < 0.22:
                emit(RotationAdjustEvent(team=rng.choice((HOME, AWAY)),
                                         steps=rng.randrange(-2, 8)))
            elif r < 0.24:
                emit(ServeOverrideEvent(team=rng.choice((HOME, AWAY))))
            elif r < 0.26:
                emit(RallyPointEvent(team=rng.choice((HOME, AWAY)),
                                     reason=rng.choice(("net fault", "manual",
                                                        "referee decision"))))
            else:
                srv = st.serving_team
                pid = (engine.expected_server()
                       if rng.random() < 0.92 else
                       rng.choice(st.team[srv].lineup))
                team = srv if rng.random() < 0.97 else other(srv)
                emit(ServeEvent(
                    team=team, player_id=pid, rating=pick_rating(rng),
                    trajectory=rand_traj(rng) if rng.random() < 0.5 else None,
                    ts=(round(1000.0 + len(events) * 3.5, 2)
                        if rng.random() < 0.5 else None)))
            continue

        if ph == Phase.RECEPTION:
            rcv = engine.receiving_team()
            tk = rcv if rng.random() < 0.97 else other(rcv)
            emit(ReceptionEvent(team=tk,
                                player_id=rng.choice(st.team[tk].lineup),
                                rating=pick_rating(rng),
                                overpass=rng.random() < 0.08))
            continue

        if ph == Phase.ATTACK:
            atk = st.attacking_team or st.serving_team
            tk = atk if rng.random() < 0.95 else other(atk)
            pid = rng.choice(st.team[tk].lineup)
            if rng.random() < 0.25:    # attack touched by the block
                emit(rand_blocked_attack(rng, engine, tk, pid))
            else:
                emit(AttackEvent(
                    team=tk, player_id=pid, rating=pick_rating(rng),
                    trajectory=rand_traj(rng) if rng.random() < 0.5 else None))
            continue

        if ph == Phase.DEFENSE:
            dfd = other(st.attacking_team or st.serving_team)
            if rng.random() < 0.12:    # scouter skipped the dig
                emit(AttackEvent(team=dfd,
                                 player_id=rng.choice(st.team[dfd].lineup),
                                 rating=pick_rating(rng)))
            else:
                tk = dfd if rng.random() < 0.97 else other(dfd)
                emit(DigEvent(team=tk,
                              player_id=rng.choice(st.team[tk].lineup),
                              rating=pick_rating(rng)))
            continue

    return teams, events


# --------------------------------------------------------- scripted fixtures

def scripted_corrections() -> tuple[MatchConfig, dict, list]:
    """Short sets; exercises set reopening by manual score correction,
    points after match over, and the deciding-set mid-set switch."""
    config = MatchConfig(sets_to_win=2, points_per_set=5,
                         points_deciding_set=5, deciding_set_switch_at=3)
    teams = build_teams()
    ev: list = [first_set_start(teams)]
    ev += [RallyPointEvent(team=HOME) for _ in range(5)]      # 5-0, set over
    ev.append(ManualScoreEvent(team=HOME, delta=-1))          # reopens: 4-0
    ev.append(RallyPointEvent(team=HOME))                     # 5-0 again
    # set 2 (away sweeps)
    engine = MatchEngine(config, teams)
    for e in ev:
        engine.append(e)
    ev.append(engine.suggest_next_set_start())
    engine.append(ev[-1])
    for _ in range(5):
        e = RallyPointEvent(team=AWAY)
        engine.append(e)
        ev.append(e)
    # set 3 = deciding: alternate to trigger the switch at 3, HOME wins 5-3
    ev.append(engine.suggest_next_set_start())
    engine.append(ev[-1])
    for w in (HOME, AWAY, HOME, AWAY, HOME, AWAY, HOME, HOME):
        e = RallyPointEvent(team=w)
        engine.append(e)
        ev.append(e)
    ev.append(RallyPointEvent(team=AWAY))     # after match over -> warning
    ev.append(ManualScoreEvent(team=AWAY, delta=1))
    return config, teams, ev


def scripted_warnings() -> tuple[MatchConfig, dict, list]:
    """Every illegal-input warning at least once, in a compact sequence."""
    config = MatchConfig()
    teams = build_teams()
    h = starters(teams, HOME)
    a = starters(teams, AWAY)
    lib_h = libero_of(teams, HOME)
    bad_start = SetStartEvent(
        set_number=2,                                  # wrong number
        lineups={HOME: h[:5], AWAY: a[:5] + [a[4]]},   # short + duplicate
        liberos={HOME: [h[0]], AWAY: []},              # libero in lineup
        serving_team=HOME, left_team=HOME)
    ev: list = [
        ServeEvent(team=HOME, player_id="H1"),         # serve before set start
        bad_start,
        # repair: proper set start while set "running" -> warning as well
        SetStartEvent(set_number=3,
                      lineups={HOME: h, AWAY: a},
                      liberos={HOME: [lib_h], AWAY: [libero_of(teams, AWAY)]},
                      serving_team=HOME, left_team=AWAY),
        ServeEvent(team=AWAY, player_id=a[1]),          # wrong team + player
        ReceptionEvent(team=HOME, player_id=h[4],       # after wrong serve the
                       rating=Rating.GOOD),             # server side receives
        AttackEvent(team=AWAY, player_id=a[2], rating=Rating.GOOD),
        DigEvent(team=AWAY, player_id=a[5], rating=Rating.GOOD),  # own attack
        AttackEvent(team=HOME, player_id=h[2], rating=Rating.PERFECT),
        SubstitutionEvent(team=HOME, player_out="H12", player_in=h[0]),
        LiberoSwapEvent(team=HOME, libero_id="H7", partner_id=h[1]),
        LiberoSwapEvent(team=HOME, libero_id=lib_h, partner_id=h[1]),
        TimeoutEvent(team=AWAY), TimeoutEvent(team=AWAY),
        TimeoutEvent(team=AWAY),                        # third -> warning
        RotationAdjustEvent(team=HOME, steps=-1),
        RotationAdjustEvent(team=AWAY, steps=6),        # full circle, no-op
        ServeOverrideEvent(team=AWAY),
    ]
    return config, teams, ev


def scripted_blocks() -> tuple[MatchConfig, dict, list]:
    """Pins the blocked-attack semantics: block-out kill, covered ball
    (cover dig by the attacking team, legal), covered ball with the dig
    skipped, deflection staying on the blockers' side, and a kill block."""
    config = MatchConfig()
    teams = build_teams()
    h = starters(teams, HOME)
    a = starters(teams, AWAY)
    ev: list = [first_set_start(teams)]                # HOME serves from LEFT

    # rally 1: AWAY attack deflected out -> auto kill, point AWAY (side-out)
    ev += [ServeEvent(team=HOME, player_id=h[0]),
           ReceptionEvent(team=AWAY, player_id=a[0], rating=Rating.GOOD),
           AttackEvent(team=AWAY, player_id=a[1], rating=Rating.PERFECT,
                       trajectory=(5.0, 4.5, -2.0, 10.5),
                       block_touch=(0.3, 4.5))]
    # rally 2: HOME attack covered -> HOME digs its own ball, kills next
    ev += [ServeEvent(team=AWAY, player_id=a[1]),
           ReceptionEvent(team=HOME, player_id=h[0], rating=Rating.GOOD),
           AttackEvent(team=HOME, player_id=h[1], rating=Rating.POOR,
                       trajectory=(-5.0, 4.5, -3.0, 3.0),
                       block_touch=(-0.2, 4.5)),
           DigEvent(team=HOME, player_id=h[4], rating=Rating.GOOD),
           AttackEvent(team=HOME, player_id=h[3], rating=Rating.PERFECT)]
    # rally 3: AWAY attack tips off the block, stays on HOME side (in play),
    # HOME digs and its counter-attack is kill-blocked ('!', one segment)
    ev += [ServeEvent(team=HOME, player_id=h[1]),      # side-out rotated H
           ReceptionEvent(team=AWAY, player_id=a[2], rating=Rating.GOOD),
           AttackEvent(team=AWAY, player_id=a[3], rating=Rating.GOOD,
                       trajectory=(4.0, 3.0, -4.0, 4.0),
                       block_touch=(0.5, 3.0)),
           DigEvent(team=HOME, player_id=h[5], rating=Rating.GOOD),
           AttackEvent(team=HOME, player_id=h[2], rating=Rating.ERROR,
                       trajectory=(-4.0, 4.5, -0.3, 4.5))]
    # rally 4: covered ball, cover dig skipped -> implicit-dig attack
    ev += [ServeEvent(team=AWAY, player_id=a[2]),      # side-out rotated A
           ReceptionEvent(team=HOME, player_id=h[2], rating=Rating.GOOD),
           AttackEvent(team=HOME, player_id=h[3], rating=Rating.POOR,
                       trajectory=(-4.5, 5.0, -2.5, 6.0),
                       block_touch=(-0.4, 5.0)),
           AttackEvent(team=HOME, player_id=h[4], rating=Rating.GOOD,
                       trajectory=(-3.0, 6.0, 6.0, 2.0))]
    return config, teams, ev


def scripted_libero() -> tuple[MatchConfig, dict, list]:
    """Pins the automatic libero exchange: manual first entry, forced
    front-row exit, no blind re-entry without a known partner, deferral
    while the middle serves at P1, role-fallback re-entry and learned-
    pairing re-entry at serve-receive."""
    config = MatchConfig()
    teams = build_teams()
    lib = libero_of(teams, HOME)
    engine = MatchEngine(config, teams)
    ev: list = []

    def emit(e) -> None:
        engine.append(e)
        ev.append(e)
        drain_auto_swaps(engine, ev)

    def home_wins_receiving() -> None:      # side-out: HOME rotates
        lineup = engine.state.team[HOME].lineup
        emit(ServeEvent(team=AWAY, player_id=engine.expected_server()))
        emit(ReceptionEvent(team=HOME, player_id=lineup[5],
                            rating=Rating.GOOD))
        emit(AttackEvent(team=HOME, player_id=lineup[1],
                         rating=Rating.PERFECT))

    def home_loses_serving() -> None:       # AWAY point: HOME receives next
        emit(ServeEvent(team=HOME, player_id=engine.expected_server(),
                        rating=Rating.ERROR))

    emit(SetStartEvent(
        set_number=1,
        lineups={tk: starters(teams, tk) for tk in (HOME, AWAY)},
        liberos={tk: [libero_of(teams, tk)] for tk in (HOME, AWAY)},
        serving_team=AWAY, left_team=HOME))
    # manual first entry: libero for the P5 middle (H5)
    emit(LiberoSwapEvent(team=HOME, libero_id=lib, partner_id="H5"))
    home_wins_receiving()    # rotation puts the libero at P4 -> forced exit
    home_loses_serving()     # no partner in the back row -> no blind entry
    home_wins_receiving()    # middle H3 rotates to P1 and must serve first
    home_loses_serving()     # serve-receive: back-row middle H3 -> fallback
    home_wins_receiving()    # libero rides along to P6 (back row, stays)
    home_loses_serving()     # libero already on court -> nothing to do
    home_wins_receiving()    # libero to P5
    home_loses_serving()
    home_wins_receiving()    # libero to P4 -> forced exit, H3 returns
    home_loses_serving()     # serve-receive: learned partner H5 at P6 enters
    return config, teams, ev


def scripted_unregistered_libero() -> tuple[MatchConfig, dict, list]:
    """Pins adopting a libero the scouter never designated: HOME starts the
    set with no libero registered, so the first exchange registers the
    roster libero (warning, no substitution spent) and the automatic cycle
    then runs exactly as it would have had they been designated up front."""
    config = MatchConfig()
    teams = build_teams()
    lib = libero_of(teams, HOME)
    engine = MatchEngine(config, teams)
    ev: list = []

    def emit(e) -> None:
        engine.append(e)
        ev.append(e)
        drain_auto_swaps(engine, ev)

    def home_wins_receiving() -> None:      # side-out: HOME rotates
        lineup = engine.state.team[HOME].lineup
        emit(ServeEvent(team=AWAY, player_id=engine.expected_server()))
        emit(ReceptionEvent(team=HOME, player_id=lineup[5],
                            rating=Rating.GOOD))
        emit(AttackEvent(team=HOME, player_id=lineup[1],
                         rating=Rating.PERFECT))

    def home_loses_serving() -> None:       # AWAY point: HOME receives next
        emit(ServeEvent(team=HOME, player_id=engine.expected_server(),
                        rating=Rating.ERROR))

    emit(SetStartEvent(
        set_number=1,
        lineups={tk: starters(teams, tk) for tk in (HOME, AWAY)},
        liberos={HOME: [], AWAY: [libero_of(teams, AWAY)]},   # HOME: none
        serving_team=AWAY, left_team=HOME))
    # the tap that designates: registers H12 and exchanges, no sub spent
    emit(LiberoSwapEvent(team=HOME, libero_id=lib, partner_id="H5"))
    home_wins_receiving()    # rotation puts the libero at P4 -> forced exit
    home_loses_serving()     # no partner in the back row -> no blind entry
    home_wins_receiving()    # middle H3 rotates to P1 and must serve first
    home_loses_serving()     # serve-receive: back-row middle H3 -> fallback
    home_wins_receiving()    # libero rides along to P6 (back row, stays)
    return config, teams, ev


# -------------------------------------------------------------------- main

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.json"):
        old.unlink()

    fixtures = []
    cfg, teams, ev = scripted_corrections()
    fixtures.append(run_fixture("scripted-corrections", cfg, teams, ev))
    cfg, teams, ev = scripted_warnings()
    fixtures.append(run_fixture("scripted-warnings", cfg, teams, ev))
    cfg, teams, ev = scripted_blocks()
    fixtures.append(run_fixture("scripted-blocks", cfg, teams, ev))
    cfg, teams, ev = scripted_libero()
    fixtures.append(run_fixture("scripted-libero", cfg, teams, ev))
    cfg, teams, ev = scripted_unregistered_libero()
    fixtures.append(run_fixture("scripted-unregistered-libero", cfg, teams, ev))

    variants = [
        ("default", MatchConfig(), (1, 2, 3)),
        # auto_libero off: every exchange manual, helper must stay None
        ("bo3-short", MatchConfig(sets_to_win=2, points_per_set=15,
                                  points_deciding_set=15,
                                  auto_libero=False), (4, 5)),
        ("libero-serve", MatchConfig(libero_may_serve=True), (6,)),
        ("sprint", MatchConfig(sets_to_win=3, points_per_set=5,
                               points_deciding_set=5,
                               deciding_set_switch_at=3), (7, 8)),
    ]
    for label, config, seeds in variants:
        for seed in seeds:
            teams, events = random_match(seed, config)
            fixtures.append(run_fixture(f"random-{label}-seed{seed}",
                                        config, teams, events))

    total_steps = 0
    for f in fixtures:
        path = OUT_DIR / f"{f['name']}.json"
        path.write_text(json.dumps(f, separators=(",", ":")),
                        encoding="utf-8")
        total_steps += len(f["steps"])
        print(f"{path.name}: {len(f['steps'])} steps")
    print(f"{len(fixtures)} fixtures, {total_steps} steps -> {OUT_DIR}")


if __name__ == "__main__":
    main()
