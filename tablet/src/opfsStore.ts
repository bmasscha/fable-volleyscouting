// Origin Private File System (OPFS) storage layer.
//
// IndexedDB and localStorage can be evicted or wiped by the browser when a
// user clears browsing history / site data. OPFS provides an additional high-
// performance virtual file system layer inside navigator.storage.getDirectory().
//
// Storing full application backup snapshots in OPFS allows auto-recovery on
// startup if IndexedDB is cleared, or serves as a fast secondary backup.

export const DEFAULT_OPFS_BACKUP_FILE = "fable_full_backup.json";

/** Check if the Origin Private File System API is supported in the current environment. */
export function isOpfsSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    navigator.storage != null &&
    typeof navigator.storage.getDirectory === "function"
  );
}

/** Save text content to a file in OPFS. Returns true on success, false on failure/unsupported. */
export async function saveOpfsBackup(
  content: string,
  filename: string = DEFAULT_OPFS_BACKUP_FILE,
): Promise<boolean> {
  if (!isOpfsSupported()) {
    return false;
  }
  try {
    const root = await navigator.storage.getDirectory();
    const fileHandle = await root.getFileHandle(filename, { create: true });
    // createWritable is standard on Web / OPFS
    const writable = await fileHandle.createWritable();
    await writable.write(content);
    await writable.close();
    return true;
  } catch (error) {
    console.warn("OPFS backup write failed.", error);
    return false;
  }
}

/** Load text content from a file in OPFS. Returns string content or null if absent/failed. */
export async function loadOpfsBackup(
  filename: string = DEFAULT_OPFS_BACKUP_FILE,
): Promise<string | null> {
  if (!isOpfsSupported()) {
    return null;
  }
  try {
    const root = await navigator.storage.getDirectory();
    const fileHandle = await root.getFileHandle(filename);
    const file = await fileHandle.getFile();
    return await file.text();
  } catch (error) {
    // Expected when no backup exists yet or file was not found
    return null;
  }
}

/** Delete a backup file from OPFS. Returns true if removed, false otherwise. */
export async function deleteOpfsBackup(
  filename: string = DEFAULT_OPFS_BACKUP_FILE,
): Promise<boolean> {
  if (!isOpfsSupported()) {
    return false;
  }
  try {
    const root = await navigator.storage.getDirectory();
    await root.removeEntry(filename);
    return true;
  } catch (error) {
    return false;
  }
}
