/** Match statistics computed from the event log. Pure TypeScript, no UI imports. */

import { AttackEvent, DigEvent, ManualScoreEvent, MatchEvent, RallyPointEvent, ReceptionEvent, ServeEvent } from "./events";
import { AWAY, HOME, HOME as _HOME, RATINGS, Rating, Role, Skill, TEAM_KEYS, Team, TeamKey, other, role_abbrev } from "./models";

export const SKILL_ORDER: readonly Skill[] = [Skill.SERVE, Skill.RECEPTION, Skill.ATTACK, Skill.DIG];

const _EVENT_SKILL: Partial<Record<MatchEvent["type"], Skill>> = {
  serve: Skill.SERVE,
  reception: Skill.RECEPTION,
  attack: Skill.ATTACK,
  dig: Skill.DIG,
};

// Keys of the points-breakdown dict on TeamStats.
export const ACES = "aces";
export const KILLS = "kills";
export const OPPONENT_ERRORS = "opponent_errors";
export const MANUAL_OTHER = "manual/other";

type SkillEvent = ServeEvent | ReceptionEvent | AttackEvent | DigEvent;

function _empty_counts(): Record<Rating, number> {
  return {
    [Rating.ERROR]: 0,
    [Rating.POOR]: 0,
    [Rating.GOOD]: 0,
    [Rating.PERFECT]: 0,
  };
}

export interface SkillLine {
  counts: Record<Rating, number>;
  add(rating: Rating): void;
  count(rating: Rating): number;
  readonly total: number;
  pct(rating: Rating): number;
  readonly efficiency: number;
  readonly positive_pct: number;
}

class _SkillLine implements SkillLine {
  counts: Record<Rating, number>;

  constructor(counts: Record<Rating, number> = _empty_counts()) {
    this.counts = counts;
  }

  add(rating: Rating): void {
    this.counts[rating] = (this.counts[rating] ?? 0) + 1;
  }

  count(rating: Rating): number {
    return this.counts[rating] ?? 0;
  }

  get total(): number {
    return RATINGS.reduce((sum, rating) => sum + this.count(rating), 0);
  }

  pct(rating: Rating): number {
    /** Share of `rating` in all touches, 0..100. 0 if no touches. */
    const t = this.total;
    return t ? this.count(rating) / t * 100.0 : 0.0;
  }

  get efficiency(): number {
    /** (perfect - errors) / total * 100. 0 if no touches. */
    const t = this.total;
    if (!t) {
      return 0.0;
    }
    return (this.count(Rating.PERFECT) - this.count(Rating.ERROR)) / t * 100.0;
  }

  get positive_pct(): number {
    /** (perfect + good) / total * 100. 0 if no touches. */
    const t = this.total;
    if (!t) {
      return 0.0;
    }
    return (this.count(Rating.PERFECT) + this.count(Rating.GOOD)) / t * 100.0;
  }
}

export function SkillLine(counts: Record<Rating, number> = _empty_counts()): SkillLine {
  return new _SkillLine(counts);
}

function _empty_skills(): Record<Skill, SkillLine> {
  return {
    [Skill.SERVE]: SkillLine(),
    [Skill.RECEPTION]: SkillLine(),
    [Skill.ATTACK]: SkillLine(),
    [Skill.DIG]: SkillLine(),
  };
}

export interface PlayerStats {
  player_id: string;
  skills: Record<Skill, SkillLine>;
  line(skill: Skill): SkillLine;
  readonly points: number;
  readonly total_actions: number;
}

class _PlayerStats implements PlayerStats {
  player_id: string;
  skills: Record<Skill, SkillLine>;

  constructor(player_id: string, skills: Record<Skill, SkillLine> = _empty_skills()) {
    this.player_id = player_id;
    this.skills = skills;
  }

  line(skill: Skill): SkillLine {
    return this.skills[skill];
  }

  get points(): number {
    /** Directly scored points: serve aces + attack kills. */
    return this.skills[Skill.SERVE].count(Rating.PERFECT)
      + this.skills[Skill.ATTACK].count(Rating.PERFECT);
  }

  get total_actions(): number {
    return SKILL_ORDER.reduce((sum, skill) => sum + this.skills[skill].total, 0);
  }
}

export function PlayerStats(
  player_id: string,
  skills: Record<Skill, SkillLine> = _empty_skills(),
): PlayerStats {
  return new _PlayerStats(player_id, skills);
}

type PointsBreakdown = Record<string, number>;

function _empty_points_breakdown(): PointsBreakdown {
  return { [ACES]: 0, [KILLS]: 0, [OPPONENT_ERRORS]: 0, [MANUAL_OTHER]: 0 };
}

export interface TeamStats {
  players: Record<string, PlayerStats>;
  totals: Record<Skill, SkillLine>;
  points_breakdown: PointsBreakdown;
  readonly total_points: number;
}

class _TeamStats implements TeamStats {
  players: Record<string, PlayerStats>;
  totals: Record<Skill, SkillLine>;
  points_breakdown: PointsBreakdown;

  constructor(
    players: Record<string, PlayerStats> = {},
    totals: Record<Skill, SkillLine> = _empty_skills(),
    points_breakdown: PointsBreakdown = _empty_points_breakdown(),
  ) {
    this.players = players;
    this.totals = totals;
    this.points_breakdown = points_breakdown;
  }

  get total_points(): number {
    return Object.values(this.points_breakdown).reduce((sum, value) => sum + value, 0);
  }
}

export function TeamStats(
  players: Record<string, PlayerStats> = {},
  totals: Record<Skill, SkillLine> = _empty_skills(),
  points_breakdown: PointsBreakdown = _empty_points_breakdown(),
): TeamStats {
  return new _TeamStats(players, totals, points_breakdown);
}

export function compute_stats(
  events: MatchEvent[],
  teams: Partial<Record<TeamKey, Team>>,
): Record<TeamKey, TeamStats> {
  /** Replay the event log into per-team / per-player statistics.
   *
   * `teams` maps HOME/AWAY -> Team. Skill events whose player_id is not on
   * the roster of event.team are skipped gracefully (not counted anywhere).
   */
  const stats = {} as Record<TeamKey, TeamStats>;
  for (const key of TEAM_KEYS) {
    const ts = TeamStats();
    const team = teams[key];
    if (team != null) {
      for (const p of team.players) {
        ts.players[p.id] = PlayerStats(p.id);
      }
    }
    stats[key] = ts;
  }

  const errors: Record<TeamKey, number> = { [HOME]: 0, [AWAY]: 0 }; // own '!' faults per team
  const manual: Record<TeamKey, number> = { [HOME]: 0, [AWAY]: 0 }; // rally points + score deltas

  for (const e of events) {
    const skill = _EVENT_SKILL[e.type];
    if (skill != null) {
      const skill_event = e as SkillEvent;
      const team_key = skill_event.team;
      const ts = stats[team_key];
      if (ts == null) {
        continue;
      }
      if (skill_event.rating === Rating.ERROR && team_key in errors) {
        errors[team_key] += 1;
      }
      const ps = ts.players[skill_event.player_id];
      if (ps == null) {
        continue; // unknown player: skip gracefully
      }
      ps.line(skill).add(skill_event.rating);
      ts.totals[skill].add(skill_event.rating);
    } else if (e.type === "rally_point") {
      if (e.team in manual) {
        manual[e.team] += 1;
      }
    } else if (e.type === "manual_score") {
      if (e.team in manual) {
        manual[e.team] += e.delta;
      }
    }
  }

  for (const key of TEAM_KEYS) {
    const ts = stats[key];
    ts.points_breakdown[ACES] = ts.totals[Skill.SERVE].count(Rating.PERFECT);
    ts.points_breakdown[KILLS] = ts.totals[Skill.ATTACK].count(Rating.PERFECT);
    ts.points_breakdown[OPPONENT_ERRORS] = errors[other(key)];
    ts.points_breakdown[MANUAL_OTHER] = manual[key];
  }
  return stats;
}

// ---------------------------------------------------------------- exporters

const _RATING_COLS: readonly Rating[] = [Rating.ERROR, Rating.POOR, Rating.GOOD, Rating.PERFECT];

function _skill_cells(line: SkillLine): string[] {
  return [String(line.total)]
    .concat(_RATING_COLS.map((rating) => String(line.count(rating))))
    .concat([line.efficiency.toFixed(1)]);
}

function _csv_cell(cell: string): string {
  if (/["\r\n,]/.test(cell)) {
    return `"${cell.replace(/"/g, "\"\"")}"`;
  }
  return cell;
}

export function export_csv(
  stats: Partial<Record<TeamKey, TeamStats>>,
  teams: Partial<Record<TeamKey, Team>>,
): string {
  /** Render one CSV with player rows and a team-total row per team. */
  const header = ["team", "number", "name", "role"];
  for (const skill of SKILL_ORDER) {
    const s = skill;
    header.push(`${s}_total`, `${s}_err`, `${s}_poor`, `${s}_good`, `${s}_perf`, `${s}_eff_pct`);
  }
  header.push("points");

  const rows: string[][] = [header];
  for (const key of TEAM_KEYS) {
    const team = teams[key];
    const ts = stats[key];
    if (team == null || ts == null) {
      continue;
    }
    for (const player of [...team.players].sort((a, b) => a.number - b.number)) {
      const ps = ts.players[player.id] ?? PlayerStats(player.id);
      const row = [team.name, String(player.number), player.name, player.role];
      for (const skill of SKILL_ORDER) {
        row.push(..._skill_cells(ps.line(skill)));
      }
      row.push(String(ps.points));
      rows.push(row);
    }
    const total_row = [team.name, "", "TEAM TOTAL", ""];
    for (const skill of SKILL_ORDER) {
      total_row.push(..._skill_cells(ts.totals[skill]));
    }
    total_row.push(String(ts.total_points));
    rows.push(total_row);
  }

  return rows.map((row) => row.map(_csv_cell).join(",")).join("\r\n") + "\r\n";
}

const _HTML_CSS = `
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
`;

function _capitalize(text: string): string {
  return text ? text[0]!.toUpperCase() + text.slice(1) : text;
}

function _escape(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

export function export_html(
  stats: Partial<Record<TeamKey, TeamStats>>,
  teams: Partial<Record<TeamKey, Team>>,
): string {
  /** Render a self-contained printable HTML report. */
  const home = teams[_HOME];
  const away = teams[AWAY];
  const title = `${home != null ? _escape(home.name) : "Home"} vs ${away != null ? _escape(away.name) : "Away"}`;

  const parts: string[] = [
    "<!DOCTYPE html>",
    "<html><head><meta charset='utf-8'>",
    `<title>Match report - ${title}</title>`,
    `<style>${_HTML_CSS}</style></head><body>`,
    `<h1>Match report &mdash; ${title}</h1>`,
  ];

  for (const key of TEAM_KEYS) {
    const team = teams[key];
    const ts = stats[key];
    if (team == null || ts == null) {
      continue;
    }
    parts.push(`<h2>${_escape(team.name)}</h2>`);
    parts.push("<table><tr><th>#</th><th>Name</th><th>Role</th>");
    for (const skill of SKILL_ORDER) {
      const s = _escape(_capitalize(skill));
      parts.push(`<th>${s} tot</th><th>${s} !</th><th>${s} -</th><th>${s} +</th><th>${s} #</th><th>${s} eff%</th>`);
    }
    parts.push("<th>Points</th></tr>");

    for (const player of [...team.players].sort((a, b) => a.number - b.number)) {
      const ps = ts.players[player.id] ?? PlayerStats(player.id);
      const cells = [
        `<td>${player.number}</td>`,
        `<td class='name'>${_escape(player.name)}</td>`,
        `<td>${_escape(role_abbrev(player.role as Role))}</td>`,
      ];
      for (const skill of SKILL_ORDER) {
        cells.push(..._skill_cells(ps.line(skill)).map((cell) => `<td>${cell}</td>`));
      }
      cells.push(`<td>${ps.points}</td>`);
      parts.push(`<tr>${cells.join("")}</tr>`);
    }

    const total_cells = ["<td></td>", "<td class='name'>TEAM TOTAL</td>", "<td></td>"];
    for (const skill of SKILL_ORDER) {
      total_cells.push(..._skill_cells(ts.totals[skill]).map((cell) => `<td>${cell}</td>`));
    }
    total_cells.push(`<td>${ts.total_points}</td>`);
    parts.push(`<tr class='total'>${total_cells.join("")}</tr>`);
    parts.push("</table>");

    const bd = ts.points_breakdown;
    parts.push(
      `<p class='breakdown'><b>Points: ${ts.total_points}</b> `
      + `(aces ${bd[ACES]}, kills ${bd[KILLS]}, `
      + `opponent errors ${bd[OPPONENT_ERRORS]}, `
      + `manual/other ${bd[MANUAL_OTHER]})</p>`,
    );
  }

  parts.push("</body></html>");
  return parts.join("\n");
}
