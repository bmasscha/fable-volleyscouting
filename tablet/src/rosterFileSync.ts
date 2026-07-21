// Auto-write the team library to a real folder on disk via the File System
// Access API. This is the ONLY storage here that survives a manual "clear
// browsing data" (the files are outside the browser sandbox) and it points
// straight at the desktop app's rosters/ folder, so the two apps share files
// with zero conversion: each team is written as <SafeName>.json in the exact
// desktop shape (see exportTeamJson / teamExportFilename in browserStorage.ts).
//
// Availability: desktop Chrome/Edge only. Android Chrome and iPad Safari do not
// implement showDirectoryPicker, so every function here degrades to a no-op and
// the UI hides the "Link folder" control.

import { Team } from "./core/models";
import { ROSTER_STORE, openDb, requestResult, txDone } from "./matchStore";
import { exportTeamJson, importTeamsFromJson, teamExportFilename } from "./browserStorage";

// Minimal structural types for the File System Access API bits we use; the
// installed TS DOM lib does not always declare showDirectoryPicker or the
// permission methods, so we keep our own narrow surface.
type PermissionState = "granted" | "denied" | "prompt";
interface PermissionDescriptor {
  mode?: "read" | "readwrite";
}
interface FsWritable {
  write(data: string): Promise<void>;
  close(): Promise<void>;
}
interface FsFileHandle {
  createWritable(): Promise<FsWritable>;
  getFile(): Promise<{ text(): Promise<string> }>;
}
export interface FsDirectoryHandle {
  name: string;
  keys(): AsyncIterableIterator<string>;
  getFileHandle(name: string, options?: { create?: boolean }): Promise<FsFileHandle>;
  removeEntry(name: string, options?: { recursive?: boolean }): Promise<void>;
  queryPermission?(descriptor?: PermissionDescriptor): Promise<PermissionState>;
  requestPermission?(descriptor?: PermissionDescriptor): Promise<PermissionState>;
}
type DirectoryPicker = (options?: {
  mode?: "read" | "readwrite";
  id?: string;
}) => Promise<FsDirectoryHandle>;

const HANDLE_ID = "folder-handle";

interface FolderHandleRecord {
  id: string;
  handle: FsDirectoryHandle;
}

/** True on browsers that can auto-write a real roster folder (desktop
 * Chrome/Edge). Used to show or hide the "Link folder" control. */
export function isFolderSyncSupported(): boolean {
  return typeof (globalThis as { showDirectoryPicker?: DirectoryPicker }).showDirectoryPicker ===
    "function";
}

/** The currently linked folder's display name, or null when none is linked
 * (or the stored handle can no longer be read). Never throws. */
export async function linkedFolderName(): Promise<string | null> {
  const handle = await loadStoredHandle();
  return handle?.name ?? null;
}

async function loadStoredHandle(): Promise<FsDirectoryHandle | null> {
  try {
    const db = await openDb();
    const tx = db.transaction(ROSTER_STORE, "readonly");
    const record = (await requestResult(tx.objectStore(ROSTER_STORE).get(HANDLE_ID))) as
      | FolderHandleRecord
      | undefined;
    return record?.handle ?? null;
  } catch (error) {
    console.warn("Linked roster folder is unavailable.", error);
    return null;
  }
}

async function storeHandle(handle: FsDirectoryHandle | null): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(ROSTER_STORE, "readwrite");
  if (handle == null) {
    tx.objectStore(ROSTER_STORE).delete(HANDLE_ID);
  } else {
    tx.objectStore(ROSTER_STORE).put({ id: HANDLE_ID, handle });
  }
  await txDone(tx);
}

/** Prompt the user to pick a folder and remember it. Returns the folder name on
 * success, or null if the picker is unsupported or the user cancelled. */
export async function linkRosterFolder(): Promise<string | null> {
  const picker = (globalThis as { showDirectoryPicker?: DirectoryPicker }).showDirectoryPicker;
  if (picker == null) {
    return null;
  }
  try {
    const handle = await picker({ mode: "readwrite", id: "fable-rosters" });
    await storeHandle(handle);
    return handle.name;
  } catch (error) {
    // AbortError = user cancelled the picker; treat as a no-op.
    if ((error as { name?: string }).name === "AbortError") {
      return null;
    }
    console.warn("Could not link a roster folder.", error);
    return null;
  }
}

/** Forget the linked folder (the files on disk are left untouched). */
export async function unlinkRosterFolder(): Promise<void> {
  try {
    await storeHandle(null);
  } catch (error) {
    console.warn("Could not unlink the roster folder.", error);
  }
}

async function ensureWritePermission(handle: FsDirectoryHandle): Promise<boolean> {
  const descriptor: PermissionDescriptor = { mode: "readwrite" };
  if (handle.queryPermission != null) {
    if ((await handle.queryPermission(descriptor)) === "granted") {
      return true;
    }
  }
  if (handle.requestPermission != null) {
    return (await handle.requestPermission(descriptor)) === "granted";
  }
  // No permission API: assume usable (older implementations grant on pick).
  return true;
}

// ---- pure directory read/write (handle injected, unit-testable) ----------
//
// These take a directory handle directly, so a test can drive them with an
// in-memory fake. The public wrappers below add the handle-load + permission
// steps (which need the real browser + native picker, not unit-testable).

/** Read every single-team file in a folder, skipping non-team JSON. */
export async function readTeamsFromDir(handle: FsDirectoryHandle): Promise<Team[]> {
  const teams: Team[] = [];
  for await (const name of handle.keys()) {
    if (!name.toLowerCase().endsWith(".json")) {
      continue;
    }
    try {
      const file = await (await handle.getFileHandle(name)).getFile();
      teams.push(...importTeamsFromJson(await file.text()));
    } catch {
      // Skip a file that is not a team (or cannot be read).
    }
  }
  return teams;
}

/** Write one <SafeName>.json per team (desktop shape) and remove stale
 * single-team files whose team no longer exists. Non-team JSON is left be. */
export async function writeTeamsToDir(handle: FsDirectoryHandle, teams: Team[]): Promise<void> {
  const wanted = new Map<string, Team>();
  for (const team of teams) {
    wanted.set(teamExportFilename(team), team);
  }
  // Write / update every current team.
  for (const [filename, team] of wanted) {
    const fileHandle = await handle.getFileHandle(filename, { create: true });
    const writable = await fileHandle.createWritable();
    await writable.write(exportTeamJson(team));
    await writable.close();
  }
  // Remove orphaned single-team files (e.g. left by a renamed/deleted team).
  const stale: string[] = [];
  for await (const name of handle.keys()) {
    if (wanted.has(name) || !name.toLowerCase().endsWith(".json")) {
      continue;
    }
    try {
      const file = await (await handle.getFileHandle(name)).getFile();
      importTeamsFromJson(await file.text()); // throws if not a team file
      stale.push(name);
    } catch {
      // Not a recognizable team file -> leave it alone.
    }
  }
  for (const name of stale) {
    await handle.removeEntry(name);
  }
}

/** Import every single-team file already present in the linked folder, so a
 * freshly linked desktop rosters/ folder seeds the library. Non-team JSON is
 * skipped. Returns [] when nothing is linked / readable. */
export async function importTeamsFromLinkedFolder(): Promise<Team[]> {
  const handle = await loadStoredHandle();
  if (handle == null || !(await ensureWritePermission(handle))) {
    return [];
  }
  try {
    return await readTeamsFromDir(handle);
  } catch (error) {
    console.warn("Could not read the linked roster folder.", error);
    return [];
  }
}

/** Write the library to the linked folder. Fire-and-forget from the save path;
 * a no-op (returns false) when nothing is linked or permission is not granted. */
export async function syncTeamsToFolder(teams: Team[]): Promise<boolean> {
  const handle = await loadStoredHandle();
  if (handle == null || !(await ensureWritePermission(handle))) {
    return false;
  }
  try {
    await writeTeamsToDir(handle, teams);
    return true;
  } catch (error) {
    console.warn("Could not sync teams to the linked folder.", error);
    return false;
  }
}
