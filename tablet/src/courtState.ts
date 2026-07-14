import { MatchEngine, Phase } from "./core/engine";
import { MatchEvent, Trajectory } from "./core/events";
import { Mode, acting_setter_slot, formation_xy } from "./core/formations";
import { Role, TeamKey, TEAM_KEYS, other, team_player } from "./core/models";
import { COURT_HALF_LENGTH, COURT_WIDTH } from "./core/rotation";

export interface CandidateSelection {
  teamKey: TeamKey;
  playerId: string;
}

export interface PendingAttackState {
  teamKey: TeamKey;
  playerId: string;
  trajectory: Trajectory;
}

export interface CourtTokenSpec {
  teamKey: TeamKey;
  playerId: string;
  number: number;
  name: string;
  color: string;
  badge: string;
  x: number;
  y: number;
  highlight: boolean;
  serving: boolean;
}

export interface CourtTrajectorySpec {
  kind: "serve" | "attack";
  trajectory: Trajectory;
  opacity: number;
}

export const SETTER_TOKEN_COLOR = "#1565c0";
export const LIBERO_TOKEN_COLOR = "#c62828";
export const OUT_TOLERANCE = 0.4;

export function teamMode(engine: MatchEngine, teamKey: TeamKey, formationsEnabled: boolean): Mode {
  const state = engine.state;
  if (!formationsEnabled) {
    return Mode.GRID;
  }
  if (state.phase === Phase.AWAIT_SERVE) {
    return teamKey === state.serving_team ? Mode.SERVE_BASE : Mode.RECEIVE;
  }
  if (state.phase === Phase.RECEPTION) {
    return teamKey === state.serving_team ? Mode.DEFENSE : Mode.RECEIVE;
  }
  if (state.phase === Phase.ATTACK || state.phase === Phase.DEFENSE) {
    return teamKey === state.attacking_team ? Mode.OFFENSE : Mode.DEFENSE;
  }
  return Mode.GRID;
}

export function displayedPositions(
  engine: MatchEngine,
  teamKey: TeamKey,
  formationsEnabled: boolean,
): Record<string, [number, number]> {
  const state = engine.state;
  const teamState = state.team[teamKey];
  const side = engine.side_of(teamKey);
  const roles: Record<number, Role> = {};

  teamState.lineup.forEach((playerId, index) => {
    const player = team_player(engine.teams[teamKey], playerId);
    roles[index] = playerId in teamState.libero_replaced || teamState.liberos.includes(playerId)
      ? Role.LIBERO
      : player?.role ?? Role.UNIVERSAL;
  });

  const xy = formation_xy(acting_setter_slot(roles), teamMode(engine, teamKey, formationsEnabled), side);
  return Object.fromEntries(teamState.lineup.map((playerId, index) => [playerId, xy[index]]));
}

export function nearestPlayerId(
  engine: MatchEngine,
  teamKey: TeamKey,
  x: number,
  y: number,
  formationsEnabled: boolean,
): string | null {
  let bestPlayerId: string | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  const positions = displayedPositions(engine, teamKey, formationsEnabled);

  Object.entries(positions).forEach(([playerId, [px, py]]) => {
    const distance = (px - x) ** 2 + (py - y) ** 2;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestPlayerId = playerId;
    }
  });

  return bestPlayerId;
}

export function buildCourtTokens(
  engine: MatchEngine,
  selected: CandidateSelection | null,
  formationsEnabled: boolean,
): CourtTokenSpec[] {
  const state = engine.state;
  const tokens: CourtTokenSpec[] = [];

  TEAM_KEYS.forEach((teamKey) => {
    const team = engine.teams[teamKey];
    const teamState = state.team[teamKey];
    const positions = displayedPositions(engine, teamKey, formationsEnabled);

    teamState.lineup.forEach((playerId, index) => {
      const player = team_player(team, playerId);
      if (player == null) {
        return;
      }
      const isLibero = teamState.liberos.includes(playerId) || player.role === Role.LIBERO;
      const isSetter = player.role === Role.SETTER;
      tokens.push({
        teamKey,
        playerId,
        number: player.number,
        name: player.name,
        color: isLibero ? LIBERO_TOKEN_COLOR : isSetter ? SETTER_TOKEN_COLOR : team.color,
        badge: isLibero ? "L" : isSetter ? "S" : "",
        x: positions[playerId]![0],
        y: positions[playerId]![1],
        highlight: selected?.teamKey === teamKey && selected.playerId === playerId,
        serving: teamKey === state.serving_team && index === 0,
      });
    });
  });

  return tokens;
}

export function serveIsOut(
  engine: MatchEngine,
  servingTeam: TeamKey,
  x2: number,
  y2: number,
  tolerance = OUT_TOLERANCE,
): boolean {
  const opponentSide = engine.side_of(other(servingTeam));
  if (!(-tolerance <= y2 && y2 <= COURT_WIDTH + tolerance)) {
    return true;
  }
  if (opponentSide === "left") {
    return !(-COURT_HALF_LENGTH - tolerance <= x2 && x2 <= tolerance);
  }
  return !(0 - tolerance <= x2 && x2 <= COURT_HALF_LENGTH + tolerance);
}

/** True between rallies (point scored, set or match over): the finished
 * rally's trajectories should fade off the court instead of lingering
 * until the next serve is drawn. Derived from engine state so an undo
 * that reopens the rally brings the arrows straight back. */
export function trajectoriesExpired(engine: MatchEngine): boolean {
  const phase = engine.state.phase;
  return phase === Phase.AWAIT_SERVE || phase === Phase.SET_OVER || phase === Phase.MATCH_OVER;
}

export function recentCourtTrajectories(
  events: MatchEvent[],
  limit = 5,
): CourtTrajectorySpec[] {
  let start = -1;
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (event.type === "serve") {
      start = index;
      break;
    }
    if (event.type === "set_start") {
      break;
    }
  }

  if (start < 0) {
    return [];
  }

  const trajectoryEvents = events
    .slice(start)
    .filter((event): event is Extract<MatchEvent, { type: "serve" | "attack" }> => (
      (event.type === "serve" || event.type === "attack") && event.trajectory != null
    ));

  const recent = trajectoryEvents.slice(-limit);
  return recent.map((event, index) => ({
    kind: event.type,
    trajectory: event.trajectory!,
    opacity: Math.max(0.2, 1 - (recent.length - index - 1) * 0.2),
  }));
}
