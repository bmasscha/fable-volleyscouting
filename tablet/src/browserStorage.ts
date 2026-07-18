import { MatchEvent, event_from_dict, event_to_dict } from "./core/events";
import {
  AWAY,
  HOME,
  MatchConfig,
  Team,
  TeamKey,
  config_from_dict,
  config_to_dict,
  team_from_dict,
  team_to_dict,
} from "./core/models";
import { SystemSpec } from "./core/systems";
import { deserialize_system, serialize_system } from "./core/user_systems";
import { createSeedRosterLibrary, sortTeams } from "./setup";

export interface MatchSnapshot {
  config: MatchConfig;
  teams: Record<TeamKey, Team>;
  events: MatchEvent[];
  lastWarnings: string[];
  savedAt: number | null;
}

interface StoredSnapshot {
  version: 1;
  config: Record<string, unknown>;
  teams: Record<string, Record<string, unknown>>;
  events: Record<string, unknown>[];
  lastWarnings: string[];
  savedAt: number | null;
}

interface StoredRosterLibrary {
  version: 1;
  teams: Record<string, unknown>[];
}

interface StoredUserSystems {
  version: 1;
  systems: Record<string, unknown>[];
}

export const AUTOSAVE_KEY = "fable-scouter.tablet.autosave";
export const ROSTER_LIBRARY_KEY = "fable-scouter.tablet.roster-library";
export const USER_SYSTEMS_KEY = "fable-scouter.tablet.user-systems";

function readStorageItem(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch (error) {
    console.warn("Autosave storage is unavailable for reads.", error);
    return null;
  }
}

function writeStorageItem(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch (error) {
    console.warn("Autosave storage is unavailable for writes.", error);
    return false;
  }
}

function removeStorageItem(key: string): boolean {
  try {
    localStorage.removeItem(key);
    return true;
  } catch (error) {
    console.warn("Autosave storage is unavailable for deletes.", error);
    return false;
  }
}

export function saveAutosave(snapshot: MatchSnapshot): boolean {
  const stored: StoredSnapshot = {
    version: 1,
    config: config_to_dict(snapshot.config),
    teams: {
      [HOME]: team_to_dict(snapshot.teams[HOME]),
      [AWAY]: team_to_dict(snapshot.teams[AWAY]),
    },
    events: snapshot.events.map((event) => event_to_dict(event)),
    lastWarnings: [...snapshot.lastWarnings],
    savedAt: snapshot.savedAt,
  };
  return writeStorageItem(AUTOSAVE_KEY, JSON.stringify(stored));
}

export function loadAutosave(): MatchSnapshot | null {
  const raw = readStorageItem(AUTOSAVE_KEY);
  if (raw == null) {
    return null;
  }
  try {
    const stored = JSON.parse(raw) as Partial<StoredSnapshot>;
    if (stored.teams?.[HOME] == null || stored.teams?.[AWAY] == null) {
      throw new Error("missing teams");
    }
    return {
      config: config_from_dict(stored.config ?? {}),
      teams: {
        [HOME]: team_from_dict(stored.teams[HOME]),
        [AWAY]: team_from_dict(stored.teams[AWAY]),
      },
      events: (stored.events ?? []).map((event) => event_from_dict(event)),
      lastWarnings: Array.isArray(stored.lastWarnings)
        ? stored.lastWarnings.filter((warning): warning is string => typeof warning === "string")
        : [],
      savedAt: typeof stored.savedAt === "number" ? stored.savedAt : null,
    };
  } catch {
    clearAutosave();
    return null;
  }
}

export function clearAutosave(): boolean {
  return removeStorageItem(AUTOSAVE_KEY);
}

export function saveRosterLibrary(teams: Team[]): boolean {
  const stored: StoredRosterLibrary = {
    version: 1,
    teams: sortTeams(teams).map((team) => team_to_dict(team)),
  };
  return writeStorageItem(ROSTER_LIBRARY_KEY, JSON.stringify(stored));
}

export function loadRosterLibrary(): Team[] {
  const raw = readStorageItem(ROSTER_LIBRARY_KEY);
  if (raw == null) {
    const seeded = createSeedRosterLibrary();
    saveRosterLibrary(seeded);
    return seeded;
  }
  try {
    const stored = JSON.parse(raw) as Partial<StoredRosterLibrary>;
    const teams = Array.isArray(stored.teams)
      ? stored.teams.map((team) => team_from_dict(team))
      : [];
    return sortTeams(teams);
  } catch {
    const seeded = createSeedRosterLibrary();
    saveRosterLibrary(seeded);
    return seeded;
  }
}

/** Persist the imported custom systems as their serialized (validated)
 * dicts, so storage is checked on the way out too. Returns whether the
 * write succeeded. */
export function saveUserSystems(specs: SystemSpec[]): boolean {
  const stored: StoredUserSystems = {
    version: 1,
    systems: specs.map((spec) => serialize_system(spec)),
  };
  return writeStorageItem(USER_SYSTEMS_KEY, JSON.stringify(stored));
}

/** Load the imported custom systems, validating each stored dict on the
 * way in. Corrupt or unreadable storage yields [] -- never throws (a bad
 * blob must not stop the app from starting). Individually invalid entries
 * are skipped. */
export function loadUserSystems(): SystemSpec[] {
  const raw = readStorageItem(USER_SYSTEMS_KEY);
  if (raw == null) {
    return [];
  }
  try {
    const stored = JSON.parse(raw) as Partial<StoredUserSystems>;
    if (!Array.isArray(stored.systems)) {
      return [];
    }
    const specs: SystemSpec[] = [];
    for (const entry of stored.systems) {
      try {
        specs.push(deserialize_system(entry));
      } catch {
        // Skip an individually corrupt system rather than dropping all.
      }
    }
    return specs;
  } catch {
    return [];
  }
}
