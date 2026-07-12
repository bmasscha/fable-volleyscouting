"""Match statistics computed from the event log. Pure Python, no Qt imports."""
from __future__ import annotations

import csv
import html
from dataclasses import dataclass, field

from .events import (
    AttackEvent,
    DigEvent,
    Event,
    ManualScoreEvent,
    RallyPointEvent,
    ReceptionEvent,
    ServeEvent,
)
from .models import HOME, AWAY, Rating, Skill, Team, other

SKILL_ORDER = (Skill.SERVE, Skill.RECEPTION, Skill.ATTACK, Skill.DIG)

_EVENT_SKILL: dict[type, Skill] = {
    ServeEvent: Skill.SERVE,
    ReceptionEvent: Skill.RECEPTION,
    AttackEvent: Skill.ATTACK,
    DigEvent: Skill.DIG,
}

# Keys of the points-breakdown dict on TeamStats.
ACES = "aces"
KILLS = "kills"
OPPONENT_ERRORS = "opponent_errors"
MANUAL_OTHER = "manual/other"


def _empty_counts() -> dict[Rating, int]:
    return {r: 0 for r in Rating}


@dataclass
class SkillLine:
    """Rating tally for one skill (one player or a whole team)."""
    counts: dict[Rating, int] = field(default_factory=_empty_counts)

    def add(self, rating: Rating) -> None:
        self.counts[rating] = self.counts.get(rating, 0) + 1

    def count(self, rating: Rating) -> int:
        return self.counts.get(rating, 0)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def pct(self, rating: Rating) -> float:
        """Share of `rating` in all touches, 0..100. 0 if no touches."""
        t = self.total
        return self.count(rating) / t * 100.0 if t else 0.0

    @property
    def efficiency(self) -> float:
        """(perfect - errors) / total * 100. 0 if no touches."""
        t = self.total
        if not t:
            return 0.0
        return (self.count(Rating.PERFECT) - self.count(Rating.ERROR)) / t * 100.0

    @property
    def positive_pct(self) -> float:
        """(perfect + good) / total * 100. 0 if no touches."""
        t = self.total
        if not t:
            return 0.0
        return (self.count(Rating.PERFECT) + self.count(Rating.GOOD)) / t * 100.0


def _empty_skills() -> dict[Skill, SkillLine]:
    return {s: SkillLine() for s in SKILL_ORDER}


@dataclass
class PlayerStats:
    player_id: str
    skills: dict[Skill, SkillLine] = field(default_factory=_empty_skills)

    def line(self, skill: Skill) -> SkillLine:
        return self.skills[skill]

    @property
    def points(self) -> int:
        """Directly scored points: serve aces + attack kills."""
        return (self.skills[Skill.SERVE].count(Rating.PERFECT)
                + self.skills[Skill.ATTACK].count(Rating.PERFECT))

    @property
    def total_actions(self) -> int:
        return sum(line.total for line in self.skills.values())


@dataclass
class TeamStats:
    players: dict[str, PlayerStats] = field(default_factory=dict)
    totals: dict[Skill, SkillLine] = field(default_factory=_empty_skills)
    points_breakdown: dict[str, int] = field(
        default_factory=lambda: {ACES: 0, KILLS: 0, OPPONENT_ERRORS: 0,
                                 MANUAL_OTHER: 0})

    @property
    def total_points(self) -> int:
        return sum(self.points_breakdown.values())


def compute_stats(events: list[Event], teams: dict[str, Team]) -> dict[str, TeamStats]:
    """Replay the event log into per-team / per-player statistics.

    `teams` maps HOME/AWAY -> Team. Skill events whose player_id is not on
    the roster of event.team are skipped gracefully (not counted anywhere).
    """
    stats: dict[str, TeamStats] = {}
    for key in (HOME, AWAY):
        ts = TeamStats()
        team = teams.get(key)
        if team is not None:
            for p in team.players:
                ts.players[p.id] = PlayerStats(player_id=p.id)
        stats[key] = ts

    errors: dict[str, int] = {HOME: 0, AWAY: 0}      # own '!' faults per team
    manual: dict[str, int] = {HOME: 0, AWAY: 0}      # rally points + score deltas

    for e in events:
        skill = _EVENT_SKILL.get(type(e))
        if skill is not None:
            team_key = e.team
            ts = stats.get(team_key)
            if ts is None:
                continue
            if e.rating == Rating.ERROR and team_key in errors:
                errors[team_key] += 1
            ps = ts.players.get(e.player_id)
            if ps is None:
                continue  # unknown player: skip gracefully
            ps.line(skill).add(e.rating)
            ts.totals[skill].add(e.rating)
        elif isinstance(e, RallyPointEvent):
            if e.team in manual:
                manual[e.team] += 1
        elif isinstance(e, ManualScoreEvent):
            if e.team in manual:
                manual[e.team] += e.delta

    for key in (HOME, AWAY):
        ts = stats[key]
        ts.points_breakdown[ACES] = ts.totals[Skill.SERVE].count(Rating.PERFECT)
        ts.points_breakdown[KILLS] = ts.totals[Skill.ATTACK].count(Rating.PERFECT)
        ts.points_breakdown[OPPONENT_ERRORS] = errors[other(key)]
        ts.points_breakdown[MANUAL_OTHER] = manual[key]
    return stats


# ---------------------------------------------------------------- exporters

_RATING_COLS = (Rating.ERROR, Rating.POOR, Rating.GOOD, Rating.PERFECT)


def _skill_cells(line: SkillLine) -> list[str]:
    return ([str(line.total)]
            + [str(line.count(r)) for r in _RATING_COLS]
            + [f"{line.efficiency:.1f}"])


def export_csv(stats: dict[str, TeamStats], teams: dict[str, Team],
               path: str) -> None:
    """Write one CSV with player rows and a team-total row per team."""
    header = ["team", "number", "name", "role"]
    for skill in SKILL_ORDER:
        s = skill.value
        header += [f"{s}_total", f"{s}_err", f"{s}_poor", f"{s}_good",
                   f"{s}_perf", f"{s}_eff_pct"]
    header.append("points")

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for key in (HOME, AWAY):
            team = teams.get(key)
            ts = stats.get(key)
            if team is None or ts is None:
                continue
            for player in sorted(team.players, key=lambda p: p.number):
                ps = ts.players.get(player.id)
                if ps is None:
                    ps = PlayerStats(player_id=player.id)
                row = [team.name, str(player.number), player.name,
                       player.role.value]
                for skill in SKILL_ORDER:
                    row += _skill_cells(ps.line(skill))
                row.append(str(ps.points))
                writer.writerow(row)
            total_row = [team.name, "", "TEAM TOTAL", ""]
            for skill in SKILL_ORDER:
                total_row += _skill_cells(ts.totals[skill])
            total_row.append(str(ts.total_points))
            writer.writerow(total_row)


_HTML_CSS = """
body { font-family: 'Segoe UI', Arial, sans-serif; margin: 24px; color: #222; }
h1 { font-size: 22px; }
h2 { font-size: 18px; margin-top: 28px; }
table { border-collapse: collapse; margin-top: 8px; font-size: 13px; }
th, td { border: 1px solid #bbb; padding: 4px 8px; text-align: center; }
th { background: #2e7d32; color: #fff; }
td.name { text-align: left; }
tr.total td { font-weight: bold; background: #e8f0e8; }
.breakdown { margin-top: 10px; font-size: 14px; }
@media print { body { margin: 8px; } }
"""


def export_html(stats: dict[str, TeamStats], teams: dict[str, Team],
                path: str) -> None:
    """Write a self-contained printable HTML report."""
    esc = html.escape
    home = teams.get(HOME)
    away = teams.get(AWAY)
    title = f"{esc(home.name) if home else 'Home'} vs {esc(away.name) if away else 'Away'}"

    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>Match report - {title}</title>",
        f"<style>{_HTML_CSS}</style></head><body>",
        f"<h1>Match report &mdash; {title}</h1>",
    ]

    for key in (HOME, AWAY):
        team = teams.get(key)
        ts = stats.get(key)
        if team is None or ts is None:
            continue
        parts.append(f"<h2>{esc(team.name)}</h2>")
        parts.append("<table><tr><th>#</th><th>Name</th><th>Role</th>")
        for skill in SKILL_ORDER:
            s = esc(skill.value.capitalize())
            parts.append(f"<th>{s} tot</th><th>{s} !</th><th>{s} -</th>"
                         f"<th>{s} +</th><th>{s} #</th><th>{s} eff%</th>")
        parts.append("<th>Points</th></tr>")

        for player in sorted(team.players, key=lambda p: p.number):
            ps = ts.players.get(player.id) or PlayerStats(player_id=player.id)
            cells = [f"<td>{player.number}</td>",
                     f"<td class='name'>{esc(player.name)}</td>",
                     f"<td>{esc(player.role.abbrev)}</td>"]
            for skill in SKILL_ORDER:
                cells += [f"<td>{c}</td>" for c in _skill_cells(ps.line(skill))]
            cells.append(f"<td>{ps.points}</td>")
            parts.append("<tr>" + "".join(cells) + "</tr>")

        total_cells = ["<td></td>", "<td class='name'>TEAM TOTAL</td>", "<td></td>"]
        for skill in SKILL_ORDER:
            total_cells += [f"<td>{c}</td>" for c in _skill_cells(ts.totals[skill])]
        total_cells.append(f"<td>{ts.total_points}</td>")
        parts.append("<tr class='total'>" + "".join(total_cells) + "</tr>")
        parts.append("</table>")

        bd = ts.points_breakdown
        parts.append(
            f"<p class='breakdown'><b>Points: {ts.total_points}</b> "
            f"(aces {bd[ACES]}, kills {bd[KILLS]}, "
            f"opponent errors {bd[OPPONENT_ERRORS]}, "
            f"manual/other {bd[MANUAL_OTHER]})</p>")

    parts.append("</body></html>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
