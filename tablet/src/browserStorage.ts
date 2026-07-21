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
  // Durable identity of this match in the IndexedDB archive (see matchStore.ts).
  // Legacy autosaves without one are given a fresh id on load.
  id: string;
  // Wall-clock time the match was first saved (defaults from savedAt when absent).
  createdAt: number;
  config: MatchConfig;
  teams: Record<TeamKey, Team>;
  events: MatchEvent[];
  lastWarnings: string[];
  // false = VNL-style fixed courts: the next-set suggestion keeps the
  // current sides instead of flipping them
  switchSides: boolean;
  savedAt: number | null;
}

interface StoredSnapshot {
  version: 1;
  id?: string;
  createdAt?: number;
  config: Record<string, unknown>;
  teams: Record<string, Record<string, unknown>>;
  events: Record<string, unknown>[];
  lastWarnings: string[];
  switchSides?: boolean;
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

/** Generate a stable match id. crypto.randomUUID exists in every target
 * browser and in Node's test runner; the fallback keeps unit tests running
 * on the off chance it is absent. */
export function newMatchId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c?.randomUUID) {
    return c.randomUUID();
  }
  return `m-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Serialize a snapshot to its stored dict shape (the same one the autosave
 * blob and each IndexedDB record use). */
export function toStoredSnapshot(snapshot: MatchSnapshot): StoredSnapshot {
  return {
    version: 1,
    id: snapshot.id,
    createdAt: snapshot.createdAt,
    config: config_to_dict(snapshot.config),
    teams: {
      [HOME]: team_to_dict(snapshot.teams[HOME]),
      [AWAY]: team_to_dict(snapshot.teams[AWAY]),
    },
    events: snapshot.events.map((event) => event_to_dict(event)),
    lastWarnings: [...snapshot.lastWarnings],
    switchSides: snapshot.switchSides,
    savedAt: snapshot.savedAt,
  };
}

/** Rebuild a snapshot from a stored dict. Missing id/createdAt are backfilled
 * (legacy autosaves predate them), so an old blob loads cleanly and gains a
 * durable identity. Throws when the teams are missing. */
export function fromStoredSnapshot(stored: Partial<StoredSnapshot>): MatchSnapshot {
  if (stored.teams?.[HOME] == null || stored.teams?.[AWAY] == null) {
    throw new Error("missing teams");
  }
  const savedAt = typeof stored.savedAt === "number" ? stored.savedAt : null;
  return {
    id: typeof stored.id === "string" && stored.id.length > 0 ? stored.id : newMatchId(),
    createdAt: typeof stored.createdAt === "number" ? stored.createdAt : (savedAt ?? Date.now()),
    config: config_from_dict(stored.config ?? {}),
    teams: {
      [HOME]: team_from_dict(stored.teams[HOME]),
      [AWAY]: team_from_dict(stored.teams[AWAY]),
    },
    events: (stored.events ?? []).map((event) => event_from_dict(event)),
    lastWarnings: Array.isArray(stored.lastWarnings)
      ? stored.lastWarnings.filter((warning): warning is string => typeof warning === "string")
      : [],
    switchSides: typeof stored.switchSides === "boolean" ? stored.switchSides : true,
    savedAt,
  };
}

export function saveAutosave(snapshot: MatchSnapshot): boolean {
  return writeStorageItem(AUTOSAVE_KEY, JSON.stringify(toStoredSnapshot(snapshot)));
}

export function loadAutosave(): MatchSnapshot | null {
  const raw = readStorageItem(AUTOSAVE_KEY);
  if (raw == null) {
    return null;
  }
  try {
    return fromStoredSnapshot(JSON.parse(raw) as Partial<StoredSnapshot>);
  } catch {
    clearAutosave();
    return null;
  }
}

// ------------------------------------------------------ export / import files
//
// Export produces a file that the desktop app's core/persistence.load_match can
// read directly: it reads only {version, config, teams, events} and ignores the
// tablet-only extras. Every event keeps its wall-clock `ts`, so the file doubles
// as the dataset for later video-timestamp linking.

/** Build the portable JSON text for a match (desktop-compatible). */
export function exportMatchJson(snapshot: MatchSnapshot): string {
  const payload = {
    version: 1,
    config: config_to_dict(snapshot.config),
    teams: {
      [HOME]: team_to_dict(snapshot.teams[HOME]),
      [AWAY]: team_to_dict(snapshot.teams[AWAY]),
    },
    events: snapshot.events.map((event) => event_to_dict(event)),
    // Tablet extras; the desktop loader ignores unknown keys.
    switchSides: snapshot.switchSides,
    createdAt: snapshot.createdAt,
    savedAt: snapshot.savedAt,
    app: "fable-scouter-tablet",
  };
  return JSON.stringify(payload, null, 1);
}

/** Parse an exported match file (desktop or tablet origin) into a snapshot with
 * a fresh id -- importing never collides with or overwrites an existing match.
 * Throws on malformed input so the caller can show a banner. */
export function importMatchJson(text: string): MatchSnapshot {
  const data = JSON.parse(text) as Record<string, unknown>;
  if (data == null || typeof data !== "object") {
    throw new Error("not a match file");
  }
  const teams = data.teams as Record<string, Record<string, unknown>> | undefined;
  if (teams?.[HOME] == null || teams?.[AWAY] == null) {
    throw new Error("match file is missing teams");
  }
  if (!Array.isArray(data.events)) {
    throw new Error("match file is missing events");
  }
  return {
    id: newMatchId(),
    createdAt: typeof data.createdAt === "number" ? data.createdAt : Date.now(),
    config: config_from_dict((data.config as Record<string, unknown>) ?? {}),
    teams: {
      [HOME]: team_from_dict(teams[HOME]),
      [AWAY]: team_from_dict(teams[AWAY]),
    },
    events: (data.events as Record<string, unknown>[]).map((event) => event_from_dict(event)),
    lastWarnings: [],
    switchSides: typeof data.switchSides === "boolean" ? data.switchSides : true,
    savedAt: Date.now(),
  };
}

/** File name for an exported match: "Home-vs-Away-YYYY-MM-DD.fable.json". */
export function matchExportFilename(snapshot: MatchSnapshot): string {
  const safe = (name: string) =>
    name.replace(/[^A-Za-z0-9 _-]/g, "_").trim().replace(/\s+/g, " ") || "team";
  const d = new Date(snapshot.savedAt ?? snapshot.createdAt ?? Date.now());
  const pad = (n: number) => String(n).padStart(2, "0");
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return `${safe(snapshot.teams[HOME].name)}-vs-${safe(snapshot.teams[AWAY].name)}-${date}.fable.json`;
}

/** Trigger a browser download of text as a file. Thin DOM glue; the payload is
 * built by exportMatchJson (which is what the unit tests exercise). */
export function downloadTextFile(filename: string, text: string): void {
  const blob = new Blob([text], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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

/** Build the portable JSON text for a roster library. */
export function exportRosterLibraryJson(teams: Team[]): string {
  const payload = {
    version: 1,
    teams: sortTeams(teams).map((team) => team_to_dict(team)),
    app: "fable-scouter-tablet",
    type: "roster-library",
  };
  return JSON.stringify(payload, null, 1);
}

/** Parse an exported roster library file into a list of Teams. */
export function importRosterLibraryJson(text: string): Team[] {
  const data = JSON.parse(text) as Record<string, unknown>;
  if (data == null || typeof data !== "object") {
    throw new Error("not a valid roster library file");
  }
  const teamsData = data.teams as Record<string, unknown>[];
  if (!Array.isArray(teamsData)) {
    throw new Error("roster file is missing teams array");
  }
  const teams = teamsData.map((team) => team_from_dict(team));
  return sortTeams(teams);
}

/** File name for an exported roster library. */
export function rosterExportFilename(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  return `fable-roster-${date}.json`;
}

// ----------------------------------------------- single-team (desktop) files
//
// The desktop app stores ONE file per team in its rosters/ folder:
// core/persistence.save_team writes Team.to_dict() with indent=1 and names the
// file after the team. team_to_dict here produces the identical dict (the
// conformance contract), so these files are drop-in interchangeable both ways.

/** Portable JSON text for a single team, byte-compatible with a desktop
 * rosters/*.json file (Team.to_dict(), indent=1). */
export function exportTeamJson(team: Team): string {
  return JSON.stringify(team_to_dict(team), null, 1);
}

/** File name for a single-team file, mirroring desktop _team_filename: keep
 * alphanumerics, space, hyphen and underscore; other chars become "_"; trim;
 * fall back to "team". The Unicode \p{L}\p{N} classes match Python's
 * Unicode-aware str.isalnum(), so accented names keep the same filename on both
 * apps (and land on the same file in a shared folder). */
export function teamExportFilename(team: Team): string {
  const safe = Array.from(team.name)
    .map((c) => (/[\p{L}\p{N} _-]/u.test(c) ? c : "_"))
    .join("")
    .trim();
  return `${safe || "team"}.json`;
}

/** Parse one imported file into a list of Teams, accepting either shape:
 *   - a roster bundle  { teams: [...] }              (tablet export)
 *   - a single team    { name, players: [...] }      (desktop rosters/*.json)
 * The result is NOT sorted -- callers merge across possibly several files
 * first, then sort. Throws on anything unrecognizable so the UI can report it. */
export function importTeamsFromJson(text: string): Team[] {
  const data = JSON.parse(text) as Record<string, unknown>;
  if (data == null || typeof data !== "object") {
    throw new Error("not a valid team file");
  }
  if (Array.isArray(data.teams)) {
    return (data.teams as Record<string, unknown>[]).map((team) => team_from_dict(team));
  }
  if (typeof data.name === "string" && Array.isArray(data.players)) {
    return [team_from_dict(data)];
  }
  throw new Error("file is neither a roster library nor a single team");
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
