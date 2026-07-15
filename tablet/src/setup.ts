import { SetStartEvent } from "./core/events";
import {
  AWAY,
  HOME,
  MatchConfig,
  Player,
  Role,
  Team,
  TeamKey,
  default_config,
  make_player,
  make_team,
  role_abbrev,
  team_player,
} from "./core/models";

export const POSITION_LABELS = ["P1", "P2", "P3", "P4", "P5", "P6"] as const;
export const POSITION_HINTS = [
  "right back — first server",
  "right front",
  "middle front",
  "left front",
  "left back",
  "middle back",
] as const;

export const ROLE_ORDER: readonly Role[] = [
  Role.SETTER,
  Role.OUTSIDE,
  Role.OPPOSITE,
  Role.MIDDLE,
  Role.LIBERO,
  Role.UNIVERSAL,
] as const;

export interface MatchSetupDraft {
  homeTeamName: string;
  awayTeamName: string;
  lineups: Record<TeamKey, string[]>;
  liberos: Record<TeamKey, string[]>;
  servingTeam: TeamKey;
  leftTeam: TeamKey;
  setsToWin: number;
  pointsPerSet: number;
  pointsDecidingSet: number;
  subsPerSet: number;
  liberoMayServe: boolean;
  autoLibero: boolean;
}

export interface MatchSetupResult {
  teams: Record<TeamKey, Team>;
  config: MatchConfig;
  setStartEvent: SetStartEvent;
}

export function normalizedBoundedInteger(raw: number, minimum: number, maximum: number): number {
  if (!Number.isFinite(raw)) {
    return minimum;
  }
  return Math.max(minimum, Math.min(maximum, Math.trunc(raw)));
}

function clonePlayer(player: Player): Player {
  return { ...player };
}

export function cloneTeam(team: Team): Team {
  return {
    name: team.name,
    color: team.color,
    players: team.players.map(clonePlayer),
  };
}

function makeDefaultPlayers(prefix: string, numberOffset: number, idPrefix: string): Player[] {
  return [
    make_player(numberOffset + 1, `${prefix} Setter`, Role.SETTER, `${idPrefix}-01`),
    make_player(numberOffset + 2, `${prefix} Outside 1`, Role.OUTSIDE, `${idPrefix}-02`),
    make_player(numberOffset + 3, `${prefix} Middle 1`, Role.MIDDLE, `${idPrefix}-03`),
    make_player(numberOffset + 4, `${prefix} Opposite`, Role.OPPOSITE, `${idPrefix}-04`),
    make_player(numberOffset + 5, `${prefix} Outside 2`, Role.OUTSIDE, `${idPrefix}-05`),
    make_player(numberOffset + 6, `${prefix} Middle 2`, Role.MIDDLE, `${idPrefix}-06`),
    make_player(numberOffset + 7, `${prefix} Libero`, Role.LIBERO, `${idPrefix}-07`),
    make_player(numberOffset + 8, `${prefix} Utility`, Role.UNIVERSAL, `${idPrefix}-08`),
  ];
}

export function createSeedRosterLibrary(): Team[] {
  return sortTeams([
    make_team("Home", makeDefaultPlayers("Home", 0, "home"), "#2e7d32"),
    make_team("Away", makeDefaultPlayers("Away", 50, "away"), "#6a1b9a"),
  ]);
}

export function sortTeams(teams: Team[]): Team[] {
  return [...teams]
    .map(cloneTeam)
    .sort((left, right) => left.name.localeCompare(right.name, undefined, { sensitivity: "base" }));
}

export function createNewTeam(existingTeams: Team[]): Team {
  const existing = new Set(existingTeams.map((team) => team.name.toLocaleLowerCase()));
  const base = "New Team";
  let name = base;
  let counter = 2;
  while (existing.has(name.toLocaleLowerCase())) {
    name = `${base} ${counter}`;
    counter += 1;
  }
  return make_team(name, [], "#2e7d32");
}

export function addDraftPlayer(team: Team): Team {
  const taken = new Set(team.players.map((player) => player.number));
  let number = 1;
  while (taken.has(number)) {
    number += 1;
  }
  return {
    ...cloneTeam(team),
    players: [...team.players.map(clonePlayer), make_player(number, "New player")],
  };
}

export function prepareTeamForSave(
  draft: Team,
  existingTeams: Team[],
  originalName: string | null,
): { team: Team | null; error: string | null } {
  const name = draft.name.trim();
  if (!name) {
    return { team: null, error: "Please enter a team name." };
  }

  const existing = existingTeams.find((team) => (
    team.name.toLocaleLowerCase() === name.toLocaleLowerCase()
    && team.name !== originalName
  ));
  if (existing != null) {
    return { team: null, error: `A team named "${existing.name}" already exists.` };
  }

  const players: Player[] = [];
  const seenNumbers = new Set<number>();
  for (const [index, player] of draft.players.entries()) {
    const trimmedName = player.name.trim();
    if (!trimmedName) {
      return { team: null, error: `Player in row ${index + 1} has no name.` };
    }
    const number = normalizedBoundedInteger(player.number, 0, 99);
    if (seenNumbers.has(number)) {
      return { team: null, error: `Jersey number ${number} is used more than once.` };
    }
    seenNumbers.add(number);
    players.push({
      ...clonePlayer(player),
      number,
      name: trimmedName,
    });
  }

  return {
    team: {
      name,
      color: draft.color,
      players,
    },
    error: null,
  };
}

export function defaultTeamLineup(team: Team | null): string[] {
  if (team == null) {
    return Array.from({ length: 6 }, () => "");
  }
  const lineup = team.players
    .filter((player) => player.role !== Role.LIBERO)
    .slice(0, 6)
    .map((player) => player.id);
  while (lineup.length < 6) {
    lineup.push("");
  }
  return lineup;
}

export function defaultTeamLiberos(team: Team | null): string[] {
  if (team == null) {
    return [];
  }
  return team.players
    .filter((player) => player.role === Role.LIBERO)
    .map((player) => player.id);
}

function teamByName(library: Team[], name: string): Team | null {
  return library.find((team) => team.name === name) ?? null;
}

function normalizeLineup(lineup: string[] | undefined, team: Team | null): string[] {
  if (team == null) {
    return Array.from({ length: 6 }, () => "");
  }
  const available = new Set(team.players.map((player) => player.id));
  const used = new Set<string>();
  const normalized: string[] = [];
  for (const playerId of lineup ?? []) {
    if (normalized.length >= 6) {
      break;
    }
    if (!playerId || !available.has(playerId) || used.has(playerId)) {
      continue;
    }
    used.add(playerId);
    normalized.push(playerId);
  }
  for (const player of team.players) {
    if (normalized.length >= 6) {
      break;
    }
    if (player.role === Role.LIBERO || used.has(player.id)) {
      continue;
    }
    used.add(player.id);
    normalized.push(player.id);
  }
  while (normalized.length < 6) {
    normalized.push("");
  }
  return normalized;
}

function normalizeLiberos(liberos: string[] | undefined, team: Team | null, useDefaults: boolean): string[] {
  if (team == null) {
    return [];
  }
  if (liberos == null) {
    return useDefaults ? defaultTeamLiberos(team) : [];
  }
  const available = new Set(team.players.map((player) => player.id));
  const normalized: string[] = [];
  for (const playerId of liberos) {
    if (playerId && available.has(playerId) && !normalized.includes(playerId)) {
      normalized.push(playerId);
    }
  }
  return normalized;
}

export function makeMatchSetupDraft(
  library: Team[],
  previous: MatchSetupDraft | null = null,
): MatchSetupDraft {
  const preferredHome = library.find((team) => team.name.toLocaleLowerCase() === "home")?.name;
  const preferredAway = library.find((team) => team.name.toLocaleLowerCase() === "away")?.name;
  const firstTeam = preferredHome ?? library[0]?.name ?? "";
  const secondTeam = preferredAway && preferredAway !== firstTeam
    ? preferredAway
    : library.find((team) => team.name !== firstTeam)?.name ?? "";
  const homeTeamName = teamByName(library, previous?.homeTeamName ?? "") != null
    ? previous!.homeTeamName
    : firstTeam;
  const previousAway = previous?.awayTeamName ?? "";
  let awayTeamName = teamByName(library, previousAway) != null && previousAway !== homeTeamName
    ? previousAway
    : secondTeam;
  if (awayTeamName === homeTeamName) {
    awayTeamName = library.find((team) => team.name !== homeTeamName)?.name ?? "";
  }

  const homeTeam = teamByName(library, homeTeamName);
  const awayTeam = teamByName(library, awayTeamName);
  const defaults = default_config();

  return {
    homeTeamName,
    awayTeamName,
    lineups: {
      [HOME]: normalizeLineup(previous?.lineups[HOME], homeTeam),
      [AWAY]: normalizeLineup(previous?.lineups[AWAY], awayTeam),
    },
    liberos: {
      [HOME]: normalizeLiberos(previous?.liberos[HOME], homeTeam, previous == null),
      [AWAY]: normalizeLiberos(previous?.liberos[AWAY], awayTeam, previous == null),
    },
    servingTeam: previous?.servingTeam ?? HOME,
    leftTeam: previous?.leftTeam ?? HOME,
    setsToWin: previous?.setsToWin ?? defaults.sets_to_win,
    pointsPerSet: previous?.pointsPerSet ?? defaults.points_per_set,
    pointsDecidingSet: previous?.pointsDecidingSet ?? defaults.points_deciding_set,
    subsPerSet: previous?.subsPerSet ?? defaults.subs_per_set,
    liberoMayServe: previous?.liberoMayServe ?? defaults.libero_may_serve,
    autoLibero: previous?.autoLibero ?? defaults.auto_libero,
  };
}

export function applyTeamSelection(
  draft: MatchSetupDraft,
  teamKey: TeamKey,
  teamName: string,
  library: Team[],
): MatchSetupDraft {
  const team = teamByName(library, teamName);
  return {
    ...draft,
    homeTeamName: teamKey === HOME ? teamName : draft.homeTeamName,
    awayTeamName: teamKey === AWAY ? teamName : draft.awayTeamName,
    lineups: {
      ...draft.lineups,
      [teamKey]: defaultTeamLineup(team),
    },
    liberos: {
      ...draft.liberos,
      [teamKey]: defaultTeamLiberos(team),
    },
  };
}

export function rotateSetupLineup(playerIds: string[], steps: number): string[] {
  const amount = steps % 6;
  return [...playerIds.slice(amount), ...playerIds.slice(0, amount)];
}

function lineupName(team: Team, playerId: string): string {
  const player = team_player(team, playerId);
  return player == null ? playerId : `#${player.number} ${player.name}`;
}

export function buildMatchSetupResult(
  draft: MatchSetupDraft,
  library: Team[],
): { error: string | null; result: MatchSetupResult | null } {
  const home = teamByName(library, draft.homeTeamName);
  const away = teamByName(library, draft.awayTeamName);
  if (home == null || away == null) {
    return {
      error: "Select a team for both Home and Away. Create teams in the library first.",
      result: null,
    };
  }
  if (home.name === away.name) {
    return {
      error: "Home and Away must be two different teams.",
      result: null,
    };
  }

  const lineups: Record<TeamKey, string[]> = { [HOME]: [], [AWAY]: [] };
  const liberos: Record<TeamKey, string[]> = { [HOME]: [], [AWAY]: [] };
  for (const [teamKey, label, team] of [
    [HOME, "Home", home],
    [AWAY, "Away", away],
  ] as const) {
    const ids = draft.lineups[teamKey];
    if (ids.some((playerId) => !playerId)) {
      return {
        error: `${label} (${team.name}): assign a player to every position P1..P6.`,
        result: null,
      };
    }
    if (new Set(ids).size !== 6) {
      const duplicates = [...new Set(ids.filter((playerId) => ids.indexOf(playerId) !== ids.lastIndexOf(playerId)))];
      return {
        error: `${label} (${team.name}): each player may appear only once in the lineup (${duplicates.map((playerId) => lineupName(team, playerId)).join(", ")}).`,
        result: null,
      };
    }
    const available = new Set(team.players.map((player) => player.id));
    if (ids.some((playerId) => !available.has(playerId))) {
      return {
        error: `${label} (${team.name}): lineup contains a player missing from the roster.`,
        result: null,
      };
    }
    const selectedLiberos = draft.liberos[teamKey].filter((playerId) => available.has(playerId));
    const clashes = selectedLiberos.filter((playerId) => ids.includes(playerId));
    if (clashes.length > 0) {
      return {
        error: `${label} (${team.name}): libero(s) may not be part of the starting lineup (${clashes.map((playerId) => lineupName(team, playerId)).join(", ")}).`,
        result: null,
      };
    }
    lineups[teamKey] = [...ids];
    liberos[teamKey] = [...selectedLiberos];
  }

  const defaults = default_config();
  const config: MatchConfig = {
    ...defaults,
    sets_to_win: normalizedBoundedInteger(draft.setsToWin, 1, 9),
    points_per_set: normalizedBoundedInteger(draft.pointsPerSet, 5, 99),
    points_deciding_set: normalizedBoundedInteger(draft.pointsDecidingSet, 5, 99),
    subs_per_set: normalizedBoundedInteger(draft.subsPerSet, 0, 20),
    libero_may_serve: draft.liberoMayServe,
    auto_libero: draft.autoLibero,
  };
  return {
    error: null,
    result: {
      teams: {
        [HOME]: cloneTeam(home),
        [AWAY]: cloneTeam(away),
      },
      config,
      setStartEvent: {
        type: "set_start",
        ts: null,
        set_number: 1,
        lineups,
        liberos,
        serving_team: draft.servingTeam,
        left_team: draft.leftTeam,
      },
    },
  };
}

export function playerSummary(player: Player): string {
  return `#${player.number} ${player.name} (${role_abbrev(player.role)})`;
}
