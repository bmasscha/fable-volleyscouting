"""MatchEngine: applies the event log and derives the full match state.

Event-sourced: `events` is append-only; state is rebuilt by replay.
Undo therefore is exactly `events.pop(); replay()` and is correct across
points, rotations, substitutions and set boundaries by construction.

Rule summary implemented here (see plan section 1):
- rally scoring; set to 25 (deciding set 15), 2-point lead, no cap
- serving team wins rally -> same server, no rotation
- receiving team wins rally -> side-out: gains serve AND rotates clockwise
  (P2 becomes the new server at P1)
- sides switch after every set; in the deciding set also when the leading
  team reaches 8 points
- libero: back row only, may not serve (configurable), exchanges are not
  substitutions; engine flags mandatory swap-backs via pending_alerts()
- substitutions: 6 per set, exclusive pairs (validated as warnings)
- manual corrections are ordinary events: score +/-, serve possession,
  rotation adjust (lineup rotation only -- never score or serve)
- reception overpass: ball crosses straight back, serving team attacks
- blocked attacks (AttackEvent.block_touch): a deflection landing back in
  the attacker's own court keeps the rally alive with the ATTACKING team
  playing the next (cover) dig; any other landing behaves like a normal
  attack -- terminal ratings '#'/'!' award points exactly as always
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from . import rules
from .blocks import COVERED, classify_block_deflection
from .events import (AttackEvent, DigEvent, Event, LiberoSwapEvent,
                     ManualScoreEvent, RallyPointEvent, ReceptionEvent,
                     RotationAdjustEvent, ServeEvent, ServeOverrideEvent,
                     SetStartEvent, SubstitutionEvent, TimeoutEvent)
from .models import HOME, AWAY, MatchConfig, Rating, Team, other
from .rotation import LEFT, RIGHT, rotate_clockwise, is_front_row


class Phase(str, Enum):
    BEFORE_SET = "before_set"    # waiting for a SetStartEvent
    AWAIT_SERVE = "await_serve"  # between rallies
    RECEPTION = "reception"
    ATTACK = "attack"
    DEFENSE = "defense"
    SET_OVER = "set_over"        # waiting for confirmation / next SetStart
    MATCH_OVER = "match_over"


@dataclass
class TeamSetState:
    lineup: list[str] = field(default_factory=list)   # P1..P6 player ids
    starting_lineup: list[str] = field(default_factory=list)
    liberos: list[str] = field(default_factory=list)
    subs_used: int = 0
    sub_pairs: list[tuple[str, str]] = field(default_factory=list)
    libero_replaced: dict[str, str] = field(default_factory=dict)  # libero -> partner off court
    timeouts: int = 0


@dataclass
class MatchState:
    phase: Phase = Phase.BEFORE_SET
    set_number: int = 0
    scores: dict = field(default_factory=lambda: {HOME: 0, AWAY: 0})
    set_scores: dict = field(default_factory=lambda: {HOME: 0, AWAY: 0})
    serving_team: str = HOME
    set_first_server: str = HOME
    left_team: str = HOME
    switched_mid_set: bool = False
    attacking_team: str | None = None
    last_set_winner: str | None = None
    team: dict = field(default_factory=lambda: {HOME: TeamSetState(),
                                                AWAY: TeamSetState()})


class MatchEngine:
    def __init__(self, config: MatchConfig, teams: dict[str, Team]):
        self.config = config
        self.teams = teams
        self.events: list[Event] = []
        self.state = MatchState()

    # ------------------------------------------------------------------ api

    def append(self, event: Event) -> list[str]:
        """Validate + apply one event. Returns warnings (event is applied
        regardless -- the court is the ground truth, we only warn)."""
        warnings = self._apply(event)
        self.events.append(event)
        return warnings

    def undo(self) -> Event | None:
        if not self.events:
            return None
        removed = self.events.pop()
        self._replay()
        return removed

    def load_events(self, events: list[Event]) -> None:
        self.events = list(events)
        self._replay()

    def _replay(self) -> None:
        saved = self.events
        self.state = MatchState()
        self.events = []
        for e in saved:
            self._apply(e)
            self.events.append(e)

    # -------------------------------------------------------------- helpers

    def side_of(self, team_key: str) -> str:
        return LEFT if self.state.left_team == team_key else RIGHT

    def team_on_side(self, side: str) -> str:
        return self.state.left_team if side == LEFT else other(self.state.left_team)

    def receiving_team(self) -> str:
        return other(self.state.serving_team)

    def expected_server(self) -> str | None:
        lineup = self.state.team[self.state.serving_team].lineup
        return lineup[0] if lineup else None

    def rally_live(self) -> bool:
        return self.state.phase in (Phase.RECEPTION, Phase.ATTACK, Phase.DEFENSE)

    def set_point_info(self) -> str | None:
        """'set point HOME' / 'match point AWAY' style info, else None."""
        st = self.state
        if st.phase == Phase.BEFORE_SET or st.set_number == 0:
            return None
        target = rules.set_target(self.config, st.set_number)
        for tk in (HOME, AWAY):
            score, opp = st.scores[tk], st.scores[other(tk)]
            if score + 1 >= target and score + 1 - opp >= self.config.min_lead:
                sets_after = st.set_scores[tk] + 1
                kind = ("match point" if sets_after >= self.config.sets_to_win
                        else "set point")
                return f"{kind} {self.teams[tk].name}"
        return None

    def pending_alerts(self) -> list[str]:
        """Mandatory actions the scouter must be reminded of between rallies:
        libero swap-backs when the replaced slot rotates to the front row or
        is about to serve."""
        alerts: list[str] = []
        if self.state.phase != Phase.AWAIT_SERVE:
            return alerts
        for tk in (HOME, AWAY):
            ts = self.state.team[tk]
            for libero_id, partner_id in ts.libero_replaced.items():
                if libero_id not in ts.lineup:
                    continue
                slot = ts.lineup.index(libero_id)
                lib = self.teams[tk].player(libero_id)
                partner = self.teams[tk].player(partner_id)
                lib_n = f"#{lib.number}" if lib else "?"
                par_n = f"#{partner.number}" if partner else "?"
                if is_front_row(slot):
                    alerts.append(
                        f"{self.teams[tk].name}: libero {lib_n} rotated to the "
                        f"front row - {par_n} must return")
                elif (slot == 0 and tk == self.state.serving_team
                      and not self.config.libero_may_serve):
                    alerts.append(
                        f"{self.teams[tk].name}: libero {lib_n} is at P1 and "
                        f"may not serve - {par_n} must return")
        return alerts

    def suggest_next_set_start(self) -> SetStartEvent | None:
        """Prefill for the next set: sides switch, first serve alternates,
        lineups default to the previous starting lineups (with the libero
        exchange undone)."""
        st = self.state
        if st.phase not in (Phase.SET_OVER, Phase.BEFORE_SET):
            return None
        if st.phase == Phase.BEFORE_SET:
            return None
        return SetStartEvent(
            set_number=st.set_number + 1,
            lineups={tk: list(st.team[tk].starting_lineup) for tk in (HOME, AWAY)},
            liberos={tk: list(st.team[tk].liberos) for tk in (HOME, AWAY)},
            serving_team=other(st.set_first_server),
            left_team=other(st.left_team),
        )

    # ---------------------------------------------------------------- apply

    def _apply(self, e: Event) -> list[str]:
        handler = {
            SetStartEvent: self._on_set_start,
            ServeEvent: self._on_serve,
            ReceptionEvent: self._on_reception,
            AttackEvent: self._on_attack,
            DigEvent: self._on_dig,
            RallyPointEvent: self._on_rally_point,
            SubstitutionEvent: self._on_substitution,
            LiberoSwapEvent: self._on_libero_swap,
            ManualScoreEvent: self._on_manual_score,
            RotationAdjustEvent: self._on_rotation_adjust,
            ServeOverrideEvent: self._on_serve_override,
            TimeoutEvent: self._on_timeout,
        }.get(type(e))
        if handler is None:
            return [f"unknown event type {type(e).__name__}"]
        return handler(e)

    def _on_set_start(self, e: SetStartEvent) -> list[str]:
        w: list[str] = []
        st = self.state
        if st.phase not in (Phase.BEFORE_SET, Phase.SET_OVER):
            w.append("set started while previous set was not finished")
        if e.set_number != st.set_number + 1:
            w.append(f"unexpected set number {e.set_number} "
                     f"(expected {st.set_number + 1})")
        st.set_number = e.set_number
        st.scores = {HOME: 0, AWAY: 0}
        st.serving_team = e.serving_team
        st.set_first_server = e.serving_team
        st.left_team = e.left_team
        st.switched_mid_set = False
        st.attacking_team = None
        st.phase = Phase.AWAIT_SERVE
        for tk in (HOME, AWAY):
            lineup = list(e.lineups[tk])
            if len(lineup) != 6 or len(set(lineup)) != 6:
                w.append(f"{self.teams[tk].name}: lineup must be 6 distinct players")
            libs = list(e.liberos.get(tk, []))
            bad = [p for p in libs if p in lineup]
            if bad:
                w.append(f"{self.teams[tk].name}: libero cannot be in the "
                         f"starting lineup")
            st.team[tk] = TeamSetState(lineup=lineup, starting_lineup=list(lineup),
                                       liberos=libs)
        return w

    def _on_serve(self, e: ServeEvent) -> list[str]:
        w: list[str] = []
        st = self.state
        if st.phase != Phase.AWAIT_SERVE:
            w.append(f"serve entered during phase '{st.phase.value}'")
        if e.team != st.serving_team:
            w.append(f"{self.teams[e.team].name} served but "
                     f"{self.teams[st.serving_team].name} has serve possession")
        expected = self.expected_server()
        if expected and e.player_id != expected:
            p = self.teams[e.team].player(expected)
            w.append(f"expected server is #{p.number if p else '?'} (P1)")
        if e.rating == Rating.PERFECT:                    # ace
            self._award_point(e.team)
        elif e.rating == Rating.ERROR:                    # service fault
            self._award_point(other(e.team))
        else:
            st.phase = Phase.RECEPTION
            st.attacking_team = None
        return w

    def _on_reception(self, e: ReceptionEvent) -> list[str]:
        w: list[str] = []
        st = self.state
        if st.phase != Phase.RECEPTION:
            w.append(f"reception entered during phase '{st.phase.value}'")
        if e.team == st.serving_team:
            w.append("reception charged to the serving team")
        if e.rating == Rating.ERROR:                      # aced
            self._award_point(other(e.team))
        elif e.overpass:                                  # ball straight back
            st.phase = Phase.ATTACK
            st.attacking_team = other(e.team)
        else:
            st.phase = Phase.ATTACK
            st.attacking_team = e.team
        return w

    def _on_attack(self, e: AttackEvent) -> list[str]:
        w: list[str] = []
        st = self.state
        if st.phase == Phase.DEFENSE and e.team == other(st.attacking_team or e.team):
            # scouter skipped rating the dig -- implicit unrated defense touch
            st.attacking_team = e.team
            st.phase = Phase.ATTACK
        if st.phase not in (Phase.ATTACK,):
            w.append(f"attack entered during phase '{st.phase.value}'")
        elif st.attacking_team and e.team != st.attacking_team:
            w.append(f"attack charged to {self.teams[e.team].name} but "
                     f"{self.teams[st.attacking_team].name} has the ball")
        if e.rating == Rating.PERFECT:                    # kill (incl. block-out)
            self._award_point(e.team)
        elif e.rating == Rating.ERROR:                    # out / net / blocked down
            self._award_point(other(e.team))
        else:
            st.phase = Phase.DEFENSE
            returned = (e.block_touch is not None and e.trajectory is not None
                        and classify_block_deflection(
                            self.side_of(e.team),
                            e.trajectory[2], e.trajectory[3]) == COVERED)
            # a block deflection back into the attacker's court means the
            # attacking team itself must cover (dig) the next ball
            st.attacking_team = other(e.team) if returned else e.team
        return w

    def _on_dig(self, e: DigEvent) -> list[str]:
        w: list[str] = []
        st = self.state
        if st.phase != Phase.DEFENSE:
            w.append(f"dig entered during phase '{st.phase.value}'")
        if st.attacking_team and e.team != other(st.attacking_team):
            w.append("dig charged to the attacking team")
        if e.rating == Rating.ERROR:                      # ball hit the floor / shanked
            self._award_point(other(e.team))
        else:
            st.phase = Phase.ATTACK
            st.attacking_team = e.team                    # counter-attack
        return w

    def _on_rally_point(self, e: RallyPointEvent) -> list[str]:
        w: list[str] = []
        if self.state.phase in (Phase.BEFORE_SET, Phase.SET_OVER, Phase.MATCH_OVER):
            w.append(f"point awarded during phase '{self.state.phase.value}'")
        self._award_point(e.team)
        return w

    def _on_substitution(self, e: SubstitutionEvent) -> list[str]:
        st = self.state
        ts = st.team[e.team]
        w = []
        if self.rally_live():
            w.append("substitution during a live rally")
        w += rules.validate_substitution(
            ts.lineup, ts.liberos, ts.subs_used, ts.sub_pairs,
            e.player_out, e.player_in, self.config)
        if e.player_out in ts.lineup:
            ts.lineup[ts.lineup.index(e.player_out)] = e.player_in
        ts.subs_used += 1
        ts.sub_pairs.append((e.player_out, e.player_in))
        return w

    def _on_libero_swap(self, e: LiberoSwapEvent) -> list[str]:
        st = self.state
        ts = st.team[e.team]
        w = []
        if self.rally_live():
            w.append("libero exchange during a live rally")
        if e.libero_id not in ts.liberos:
            w.append("player is not registered as libero")
        if e.libero_id in ts.lineup:                      # libero exits
            recorded = ts.libero_replaced.get(e.libero_id, e.partner_id)
            w += rules.validate_libero_exit(recorded, e.partner_id)
            ts.lineup[ts.lineup.index(e.libero_id)] = recorded
            ts.libero_replaced.pop(e.libero_id, None)
        else:                                             # libero enters
            w += rules.validate_libero_entry(
                ts.lineup, e.partner_id,
                e.team == st.serving_team, self.config)
            if e.partner_id in ts.lineup:
                ts.lineup[ts.lineup.index(e.partner_id)] = e.libero_id
                ts.libero_replaced[e.libero_id] = e.partner_id
        return w

    def _on_manual_score(self, e: ManualScoreEvent) -> list[str]:
        st = self.state
        st.scores[e.team] = max(0, st.scores[e.team] + e.delta)
        self._check_set_end()
        return []

    def _on_rotation_adjust(self, e: RotationAdjustEvent) -> list[str]:
        w = []
        if self.rally_live():
            w.append("rotation adjusted during a live rally")
        ts = self.state.team[e.team]
        for _ in range(e.steps % 6):
            ts.lineup = rotate_clockwise(ts.lineup)
        return w

    def _on_serve_override(self, e: ServeOverrideEvent) -> list[str]:
        self.state.serving_team = e.team
        return []

    def _on_timeout(self, e: TimeoutEvent) -> list[str]:
        ts = self.state.team[e.team]
        ts.timeouts += 1
        return ["timeout limit (2 per set) exceeded"] if ts.timeouts > 2 else []

    # --------------------------------------------------------------- points

    def _award_point(self, winner: str) -> None:
        st = self.state
        st.scores[winner] += 1
        if winner != st.serving_team:
            # side-out: winner gains serve and rotates clockwise
            ts = st.team[winner]
            ts.lineup = rotate_clockwise(ts.lineup)
            st.serving_team = winner
        st.attacking_team = None
        # deciding-set mid-set side switch when the leading team reaches 8
        if (rules.is_deciding_set(self.config, st.set_number)
                and not st.switched_mid_set
                and st.scores[winner] == self.config.deciding_set_switch_at):
            st.left_team = other(st.left_team)
            st.switched_mid_set = True
        self._check_set_end()

    def _check_set_end(self) -> None:
        st = self.state
        idx = rules.set_winner(self.config, st.set_number,
                               st.scores[HOME], st.scores[AWAY])
        if st.phase in (Phase.SET_OVER, Phase.MATCH_OVER):
            # set already awarded -- never award twice; but a manual score
            # correction may re-open the set
            if idx is None and st.last_set_winner is not None:
                st.set_scores[st.last_set_winner] -= 1
                st.last_set_winner = None
                st.phase = Phase.AWAIT_SERVE
            return
        if idx is None:
            if st.phase != Phase.BEFORE_SET:
                st.phase = Phase.AWAIT_SERVE
            return
        winner = HOME if idx == 0 else AWAY
        st.set_scores[winner] += 1
        st.last_set_winner = winner
        if rules.match_winner(self.config, st.set_scores[HOME],
                              st.set_scores[AWAY]) is not None:
            st.phase = Phase.MATCH_OVER
        else:
            st.phase = Phase.SET_OVER
