import { MatchEngine } from "./core/engine";
import { LiberoSwapEvent, SetStartEvent, SubstitutionEvent } from "./core/events";
import { Player, Role, TEAM_KEYS, Team, TeamKey, team_player } from "./core/models";
import { LIBERO_TOKEN_COLOR, SETTER_TOKEN_COLOR } from "./courtState";

export interface BenchEntry {
  playerId: string;
  number: number;
  name: string;
  color: string;
  badge: string;
}

function playerAccent(
  team: Team,
  teamKey: TeamKey,
  playerId: string,
  engine: MatchEngine,
): { color: string; badge: string } {
  const player = team_player(team, playerId);
  if (player == null) {
    return { color: team.color, badge: "" };
  }
  if (engine.state.team[teamKey].liberos.includes(playerId) || player.role === Role.LIBERO) {
    return { color: LIBERO_TOKEN_COLOR, badge: "L" };
  }
  if (player.role === Role.SETTER) {
    return { color: SETTER_TOKEN_COLOR, badge: "S" };
  }
  return { color: team.color, badge: "" };
}

export function benchEntries(engine: MatchEngine, teamKey: TeamKey): BenchEntry[] {
  const team = engine.teams[teamKey];
  const teamState = engine.state.team[teamKey];
  return [...team.players]
    .filter((player) => !teamState.lineup.includes(player.id))
    .sort((left, right) => left.number - right.number)
    .map((player) => ({
      playerId: player.id,
      number: player.number,
      name: player.name,
      ...playerAccent(team, teamKey, player.id, engine),
    }));
}

export function benchSummary(engine: MatchEngine, teamKey: TeamKey): string {
  const teamState = engine.state.team[teamKey];
  return `Subs ${teamState.subs_used}/${engine.config.subs_per_set} · TO ${teamState.timeouts}/2`;
}

export function exchangeEventFor(
  engine: MatchEngine,
  teamKey: TeamKey,
  benchPlayerId: string,
  courtPlayerId: string,
): LiberoSwapEvent | SubstitutionEvent {
  const teamState = engine.state.team[teamKey];
  if (teamState.liberos.includes(benchPlayerId)) {
    return {
      type: "libero_swap",
      team: teamKey,
      libero_id: benchPlayerId,
      partner_id: courtPlayerId,
    };
  }
  if (teamState.liberos.includes(courtPlayerId)) {
    return {
      type: "libero_swap",
      team: teamKey,
      libero_id: courtPlayerId,
      partner_id: benchPlayerId,
    };
  }
  return {
    type: "substitution",
    team: teamKey,
    player_out: courtPlayerId,
    player_in: benchPlayerId,
  };
}

export function cloneSetStartEvent(event: SetStartEvent): SetStartEvent {
  return {
    ...event,
    ts: null,
    lineups: {
      home: [...event.lineups.home],
      away: [...event.lineups.away],
    },
    liberos: {
      home: [...event.liberos.home],
      away: [...event.liberos.away],
    },
  };
}

export function eligibleLineupPlayers(team: Team, liberoIds: string[]): Player[] {
  return team.players.filter((player) => !liberoIds.includes(player.id));
}

export function rotateEditedSetLineup(event: SetStartEvent, teamKey: TeamKey, steps: number): SetStartEvent {
  const amount = ((steps % 6) + 6) % 6;
  const lineup = event.lineups[teamKey];
  return {
    ...event,
    lineups: {
      ...event.lineups,
      [teamKey]: [...lineup.slice(amount), ...lineup.slice(0, amount)],
    },
  };
}

export function validateEditedSetStart(
  event: SetStartEvent,
  teams: Record<TeamKey, Team>,
): string | null {
  for (const teamKey of TEAM_KEYS) {
    const team = teams[teamKey];
    const lineup = event.lineups[teamKey];
    if (lineup.length !== 6 || lineup.some((playerId) => !playerId)) {
      return `${team.name}: assign a player to every position P1..P6.`;
    }
    if (new Set(lineup).size !== 6) {
      return `${team.name}: six distinct players are required.`;
    }
    const eligible = new Set(eligibleLineupPlayers(team, event.liberos[teamKey]).map((player) => player.id));
    if (lineup.some((playerId) => !eligible.has(playerId))) {
      return `${team.name}: starting lineup cannot include registered liberos.`;
    }
  }
  return null;
}
