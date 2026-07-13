import { Rating, Skill, Team, TeamKey, TEAM_KEYS, role_abbrev } from "./models";
import { PlayerStats, SkillLine, TeamStats } from "./stats";

export interface ReportPlayerRow {
  playerId: string | null;
  number: number | null;
  name: string;
  role: string;
  roleAbbrev: string;
  skills: Record<Skill, SkillLine>;
  points: number;
  totalActions: number;
}

export interface ReportTeamSection {
  teamKey: TeamKey;
  team: Team;
  rows: ReportPlayerRow[];
  activeRows: ReportPlayerRow[];
  totalRow: ReportPlayerRow;
  pointsBreakdown: Record<string, number>;
  totalPoints: number;
}

export const REPORT_SORT_KEY = {
  NUMBER: "number",
  NAME: "name",
  ROLE: "role",
  POINTS: "points",
  TOTAL_ACTIONS: "total_actions",
  SERVE_TOTAL: "serve_total",
  SERVE_EFFICIENCY: "serve_efficiency",
  RECEPTION_TOTAL: "reception_total",
  RECEPTION_POSITIVE: "reception_positive",
  ATTACK_TOTAL: "attack_total",
  ATTACK_KILL_PCT: "attack_kill_pct",
  ATTACK_EFFICIENCY: "attack_efficiency",
  DIG_TOTAL: "dig_total",
} as const;

export type ReportSortKey = (typeof REPORT_SORT_KEY)[keyof typeof REPORT_SORT_KEY];

const REPORT_COLLATOR = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function buildRow(
  playerId: string | null,
  number: number | null,
  name: string,
  role: string,
  roleAbbrev: string,
  skills: Record<Skill, SkillLine>,
  points: number,
  totalActions: number,
): ReportPlayerRow {
  return {
    playerId,
    number,
    name,
    role,
    roleAbbrev,
    skills,
    points,
    totalActions,
  };
}

export function buildReportSections(
  stats: Partial<Record<TeamKey, TeamStats>>,
  teams: Partial<Record<TeamKey, Team>>,
): ReportTeamSection[] {
  const sections: ReportTeamSection[] = [];
  for (const teamKey of TEAM_KEYS) {
    const team = teams[teamKey];
    const teamStats = stats[teamKey];
    if (team == null || teamStats == null) {
      continue;
    }
    const rows = [...team.players]
      .sort((left, right) => left.number - right.number)
      .map((player) => {
        const playerStats = teamStats.players[player.id] ?? PlayerStats(player.id);
        return buildRow(
          player.id,
          player.number,
          player.name,
          player.role,
          role_abbrev(player.role),
          playerStats.skills,
          playerStats.points,
          playerStats.total_actions,
        );
      });
    sections.push({
      teamKey,
      team,
      rows,
      activeRows: rows.filter((row) => row.totalActions > 0),
      totalRow: buildRow(
        null,
        null,
        "TEAM TOTAL",
        "",
        "",
        teamStats.totals,
        teamStats.total_points,
        Object.values(teamStats.totals).reduce((sum, line) => sum + line.total, 0),
      ),
      pointsBreakdown: { ...teamStats.points_breakdown },
      totalPoints: teamStats.total_points,
    });
  }
  return sections;
}

export function reportSortValue(row: ReportPlayerRow, key: ReportSortKey): number | string {
  switch (key) {
    case REPORT_SORT_KEY.NUMBER:
      return row.number ?? Number.POSITIVE_INFINITY;
    case REPORT_SORT_KEY.NAME:
      return row.name;
    case REPORT_SORT_KEY.ROLE:
      return row.roleAbbrev || row.role;
    case REPORT_SORT_KEY.POINTS:
      return row.points;
    case REPORT_SORT_KEY.TOTAL_ACTIONS:
      return row.totalActions;
    case REPORT_SORT_KEY.SERVE_TOTAL:
      return row.skills[Skill.SERVE].total;
    case REPORT_SORT_KEY.SERVE_EFFICIENCY:
      return row.skills[Skill.SERVE].efficiency;
    case REPORT_SORT_KEY.RECEPTION_TOTAL:
      return row.skills[Skill.RECEPTION].total;
    case REPORT_SORT_KEY.RECEPTION_POSITIVE:
      return row.skills[Skill.RECEPTION].positive_pct;
    case REPORT_SORT_KEY.ATTACK_TOTAL:
      return row.skills[Skill.ATTACK].total;
    case REPORT_SORT_KEY.ATTACK_KILL_PCT:
      return row.skills[Skill.ATTACK].pct(Rating.PERFECT);
    case REPORT_SORT_KEY.ATTACK_EFFICIENCY:
      return row.skills[Skill.ATTACK].efficiency;
    case REPORT_SORT_KEY.DIG_TOTAL:
      return row.skills[Skill.DIG].total;
  }
}

export function sortReportRows(
  rows: ReportPlayerRow[],
  key: ReportSortKey,
  descending = false,
): ReportPlayerRow[] {
  const ordered = [...rows].sort((left, right) => {
    const leftValue = reportSortValue(left, key);
    const rightValue = reportSortValue(right, key);
    if (typeof leftValue === "number" && typeof rightValue === "number") {
      return leftValue - rightValue;
    }
    return REPORT_COLLATOR.compare(String(leftValue), String(rightValue));
  });
  return descending ? ordered.reverse() : ordered;
}
