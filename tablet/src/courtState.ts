import { MatchEngine, MatchState, Phase } from "./core/engine";
import { MatchEvent, Trajectory } from "./core/events";
import { Mode, acting_setter_slot } from "./core/formations";
import { Role, TeamKey, TEAM_KEYS, other, team_player } from "./core/models";
import { COURT_HALF_LENGTH, COURT_WIDTH } from "./core/rotation";
import { get_system, system_xy } from "./core/systems";
import { inkFor, liberoColorFor } from "./tokenColors";

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
  ink: string;
  badge: string;
  actingSetter: boolean;
  x: number;
  y: number;
  highlight: boolean;
  serving: boolean;
}

export interface CourtTrajectorySpec {
  kind: "serve" | "attack";
  trajectory: Trajectory;
  // block deflection vertex (attacks only): draw a two-segment polyline
  // start -> vertex -> end when present.
  blockTouch?: [number, number] | null;
  opacity: number;
}

export const SETTER_TOKEN_COLOR = "#1565c0";
export const LIBERO_TOKEN_COLOR = "#c62828";
export const OUT_TOLERANCE = 0.4;

/** Which team occupies the court half a given x-coordinate falls in. Net is
 * at x = 0; the LEFT half is x < 0 (x = 0 counts as the right half). */
export function teamOnHalf(state: MatchState, x: number): TeamKey {
  return x < 0 ? state.left_team : other(state.left_team);
}

export function teamMode(
  engine: MatchEngine,
  teamKey: TeamKey,
  formationsEnabled: boolean,
  attackingOverride: TeamKey | null = null,
): Mode {
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
    // A drawn-but-unrated attack hasn't reached the engine yet, so its team
    // isn't state.attacking_team. When the caller passes the pending
    // attacker's team as the override, treat it as the offence so the
    // formations flip the moment the (counter-)attack is drawn, not only
    // once it's scored.
    const attacking = attackingOverride ?? state.attacking_team;
    return teamKey === attacking ? Mode.OFFENSE : Mode.DEFENSE;
  }
  return Mode.GRID;
}

/** Role per lineup slot, with the libero exchange applied. */
export function teamRoles(engine: MatchEngine, teamKey: TeamKey): Record<number, Role> {
  const teamState = engine.state.team[teamKey];
  const roles: Record<number, Role> = {};

  teamState.lineup.forEach((playerId, index) => {
    const player = team_player(engine.teams[teamKey], playerId);
    roles[index] = playerId in teamState.libero_replaced || teamState.liberos.includes(playerId)
      ? Role.LIBERO
      : player?.role ?? Role.UNIVERSAL;
  });

  return roles;
}

/** The setter actually running the offence: in a 6-2 the back-row one of
 * the two (the other is hitting right side). null when no setter is
 * identifiable. */
export function actingSetterId(engine: MatchEngine, teamKey: TeamKey): string | null {
  const slot = acting_setter_slot(teamRoles(engine, teamKey));
  return slot === null ? null : engine.state.team[teamKey].lineup[slot] ?? null;
}

export function displayedPositions(
  engine: MatchEngine,
  teamKey: TeamKey,
  formationsEnabled: boolean,
  attackingOverride: TeamKey | null = null,
): Record<string, [number, number]> {
  const teamState = engine.state.team[teamKey];
  const xy = system_xy(
    get_system(engine.config.systems[teamKey]),
    teamRoles(engine, teamKey),
    teamMode(engine, teamKey, formationsEnabled, attackingOverride),
    engine.side_of(teamKey),
  );
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
  showRolesEnabled = false,
  pendingAttack: PendingAttackState | null = null,
): CourtTokenSpec[] {
  const state = engine.state;
  const tokens: CourtTokenSpec[] = [];
  // a pending (drawn but unscored) attack is the acting offence, even though
  // the engine still credits the ball to the previous attacker
  const attackingOverride = pendingAttack?.teamKey ?? null;

  TEAM_KEYS.forEach((teamKey) => {
    const team = engine.teams[teamKey];
    const teamState = state.team[teamKey];
    const positions = displayedPositions(engine, teamKey, formationsEnabled, attackingOverride);
    const acting = actingSetterId(engine, teamKey);

    teamState.lineup.forEach((playerId, index) => {
      const player = team_player(team, playerId);
      if (player == null) {
        return;
      }
      const isLibero = teamState.liberos.includes(playerId) || player.role === Role.LIBERO;
      const isSetter = player.role === Role.SETTER;
      // in a 6-2 only the back-row setter runs the offence; the other one
      // is hitting right side, so only the acting one is painted as a
      // setter. Ambiguous lineup (no acting setter) -> mark both.
      const isActingSetter = isSetter && (acting === null || playerId === acting);
      const roleLabel = player.role.charAt(0).toUpperCase() + player.role.slice(1);
      // The jersey colour is the user's free choice, so a setter wears the
      // team colour with the "S" badge; the acting setter (running the
      // offence, matters in a 6-2) is flagged for a thin ring instead of a
      // special fill. The libero wears a derived, maximally distinct colour.
      const color = isLibero ? liberoColorFor(team.color) : team.color;
      tokens.push({
        teamKey,
        playerId,
        number: player.number,
        name: showRolesEnabled ? roleLabel : player.name,
        color,
        ink: inkFor(color),
        badge: isLibero ? "L" : isSetter ? "S" : "",
        actingSetter: isActingSetter && !isLibero,
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
    blockTouch: event.type === "attack" ? event.block_touch ?? null : null,
    opacity: Math.max(0.2, 1 - (recent.length - index - 1) * 0.2),
  }));
}
