// Unified full-application backup and restoration engine.
//
// Combines saved matches, team rosters, custom user systems, and video links
// into a portable `.fable.json` backup package for one-tap share/export and
// file import. Durable on-disk persistence lives in the workspace folder
// engine (workspaceStore.ts); this module only produces/consumes the portable
// backup file used to move data between devices or into a fresh install.

import { Team, team_from_dict, team_to_dict } from "./core/models";
import { SystemSpec } from "./core/systems";
import { deserialize_system, serialize_system } from "./core/user_systems";
import {
  VideoLink,
  video_link_from_dict,
  video_link_to_dict,
} from "./core/videoSync";
import {
  MatchSnapshot,
  fromStoredSnapshot,
  saveRosterLibrary,
  saveUserSystems,
  toStoredSnapshot,
} from "./browserStorage";
import {
  getAllVideoLinks,
  loadAllMatches,
  putMatches,
  saveVideoLinksBatch,
} from "./matchStore";
import { saveRosterLibraryIdb } from "./rosterStore";

export interface FullAppBackup {
  version: 1;
  app: "fable-scouter-tablet";
  type: "full-app-backup";
  exportedAt: number;
  matches: MatchSnapshot[];
  rosterLibrary: Team[];
  userSystems: SystemSpec[];
  videoLinks: Record<string, VideoLink>;
}

interface StoredFullAppBackup {
  version: 1;
  app: string;
  type: string;
  exportedAt?: number;
  matches: ReturnType<typeof toStoredSnapshot>[];
  rosterLibrary: Record<string, unknown>[];
  userSystems: Record<string, unknown>[];
  videoLinks?: Record<string, Record<string, unknown>>;
}

/** Build portable JSON string for the full app backup. */
export function exportFullAppBackupJson(
  matches: MatchSnapshot[],
  rosterLibrary: Team[],
  userSystems: SystemSpec[],
  videoLinks: Record<string, VideoLink> = {},
): string {
  const storedMatches = matches.map((m) => toStoredSnapshot(m));
  const storedRosters = rosterLibrary.map((t) => team_to_dict(t));
  const storedSystems = userSystems.map((s) => serialize_system(s));
  const storedVideoLinks: Record<string, Record<string, unknown>> = {};
  for (const [id, link] of Object.entries(videoLinks)) {
    storedVideoLinks[id] = video_link_to_dict(link);
  }

  const payload: StoredFullAppBackup = {
    version: 1,
    app: "fable-scouter-tablet",
    type: "full-app-backup",
    exportedAt: Date.now(),
    matches: storedMatches,
    rosterLibrary: storedRosters,
    userSystems: storedSystems,
    videoLinks: storedVideoLinks,
  };

  return JSON.stringify(payload, null, 1);
}

/** Parse and validate a full app backup JSON string into a FullAppBackup object.
 * Throws if the format is invalid. */
export function importFullAppBackupJson(jsonText: string): FullAppBackup {
  const data = JSON.parse(jsonText) as Partial<StoredFullAppBackup>;
  if (data == null || typeof data !== "object") {
    throw new Error("Invalid backup file: not a valid JSON object.");
  }
  if (!Array.isArray(data.matches) && !Array.isArray(data.rosterLibrary)) {
    throw new Error("Invalid backup file: missing matches or roster library.");
  }

  const matches: MatchSnapshot[] = [];
  if (Array.isArray(data.matches)) {
    for (const rawMatch of data.matches) {
      try {
        matches.push(fromStoredSnapshot(rawMatch as Partial<ReturnType<typeof toStoredSnapshot>>));
      } catch {
        // Skip individual corrupt match
      }
    }
  }

  const rosterLibrary: Team[] = [];
  if (Array.isArray(data.rosterLibrary)) {
    for (const rawTeam of data.rosterLibrary) {
      try {
        rosterLibrary.push(team_from_dict(rawTeam));
      } catch {
        // Skip corrupt team
      }
    }
  }

  const userSystems: SystemSpec[] = [];
  if (Array.isArray(data.userSystems)) {
    for (const rawSys of data.userSystems) {
      try {
        userSystems.push(deserialize_system(rawSys));
      } catch {
        // Skip corrupt system
      }
    }
  }

  const videoLinks: Record<string, VideoLink> = {};
  if (data.videoLinks != null && typeof data.videoLinks === "object") {
    for (const [id, rawLink] of Object.entries(data.videoLinks)) {
      try {
        videoLinks[id] = video_link_from_dict(rawLink);
      } catch {
        // Skip corrupt video link
      }
    }
  }

  return {
    version: 1,
    app: "fable-scouter-tablet",
    type: "full-app-backup",
    exportedAt: typeof data.exportedAt === "number" ? data.exportedAt : Date.now(),
    matches,
    rosterLibrary,
    userSystems,
    videoLinks,
  };
}

/** Restore a full backup into IndexedDB and localStorage. */
export async function restoreFullAppBackup(
  backup: FullAppBackup,
): Promise<{ matchCount: number; teamCount: number; systemCount: number }> {
  // 1. Save matches to IndexedDB
  if (backup.matches.length > 0) {
    await putMatches(backup.matches);
  }

  // 2. Save roster library to IDB and localStorage
  if (backup.rosterLibrary.length > 0) {
    await saveRosterLibraryIdb(backup.rosterLibrary);
    saveRosterLibrary(backup.rosterLibrary);
  }

  // 3. Save custom user systems to localStorage
  if (backup.userSystems.length > 0) {
    saveUserSystems(backup.userSystems);
  }

  // 4. Save video links to IDB
  if (Object.keys(backup.videoLinks).length > 0) {
    await saveVideoLinksBatch(backup.videoLinks);
  }

  return {
    matchCount: backup.matches.length,
    teamCount: backup.rosterLibrary.length,
    systemCount: backup.userSystems.length,
  };
}

/** Build full backup payload directly from storage for immediate share/export. */
export async function createFullBackupFromStorage(
  currentRosters: Team[],
  currentUserSystems: SystemSpec[],
): Promise<string> {
  const matches = await loadAllMatches();
  const videoLinks = await getAllVideoLinks();
  return exportFullAppBackupJson(matches, currentRosters, currentUserSystems, videoLinks);
}

