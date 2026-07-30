import { useRef, useState } from "preact/hooks";

import { loadUserSystems, saveUserSystems } from "./browserStorage";
import { SystemSpec } from "./core/systems";
import { parse_import, refresh_registry } from "./core/user_systems";
import { SystemEditor } from "./SystemEditor";

interface SystemsManagerProps {
  // Fired after every write with the new stored list, so a host that owns a
  // workspace folder can mirror the change to disk.
  onSystemsChanged?: (systems: SystemSpec[]) => void;
  // Fired when a stored system is dropped, so a host holding a match draft
  // that points at it can fall back to the default.
  onSystemRemoved?: (systemId: string) => void;
}

// The custom-systems bar (edit / import / stored list) plus the editor
// overlay it opens. Rendered both on its own screen from startup and inside
// match setup, so systems never have to be reached through a new match.
export function SystemsManager({ onSystemsChanged, onSystemRemoved }: SystemsManagerProps) {
  const [userSystems, setUserSystems] = useState<SystemSpec[]>(() => loadUserSystems());
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importProblems, setImportProblems] = useState<string[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);

  // The single write path shared by import, the editor's Save, and remove:
  // persist to storage, re-merge the registry (so system selects and the
  // stored-systems list below update immediately), and update local state.
  function persistUserSystems(nextList: SystemSpec[]): void {
    saveUserSystems(nextList);
    refresh_registry(nextList);
    setUserSystems(nextList);
    onSystemsChanged?.(nextList);
  }

  async function importSystemFiles(files: FileList | null): Promise<void> {
    if (files == null || files.length === 0) {
      return;
    }
    const accepted: SystemSpec[] = [];
    const problems: string[] = [];
    for (const file of Array.from(files)) {
      let text: string;
      try {
        text = await file.text();
      } catch (readError) {
        problems.push(`${file.name}: ${(readError as Error).message}`);
        continue;
      }
      const parsed = parse_import(text);
      for (const problem of parsed.problems) {
        problems.push(`${file.name}: ${problem}`);
      }
      accepted.push(...parsed.specs);
    }
    // An imported id that already exists is replaced -- the update flow.
    const merged = new Map<string, SystemSpec>();
    for (const spec of userSystems) {
      merged.set(spec.id, spec);
    }
    for (const spec of accepted) {
      merged.set(spec.id, spec);
    }
    const nextList = [...merged.values()];
    persistUserSystems(nextList);
    setImportProblems(problems);
    if (accepted.length > 0) {
      setImportMessage(`imported: ${[...new Set(accepted.map((spec) => spec.id))].join(", ")}`);
    } else {
      setImportMessage(problems.length > 0 ? null : "No systems found in the selected file(s).");
    }
  }

  // The editor's Save commits the (replaced-or-appended) list through the
  // same path the import flow uses, so system selects and the stored list
  // below refresh at once.
  function commitEditedSystems(nextList: SystemSpec[]): void {
    persistUserSystems(nextList);
    setImportProblems([]);
    setImportMessage(null);
  }

  function removeUserSystem(systemId: string): void {
    const nextList = userSystems.filter((spec) => spec.id !== systemId);
    persistUserSystems(nextList);
    setImportMessage(null);
    setImportProblems([]);
    onSystemRemoved?.(systemId);
  }

  return (
    <>
      <section className="import-systems-bar">
        <div className="button-row compact">
          <button
            type="button"
            onClick={() => setEditorOpen(true)}
          >
            Edit systems…
          </button>
          <button
            type="button"
            onClick={() => importInputRef.current?.click()}
          >
            Import systems…
          </button>
          <span className="muted">
            Create, or load custom playing systems exported from the desktop app.
          </span>
          <input
            ref={importInputRef}
            type="file"
            accept=".json,application/json"
            multiple
            style={{ display: "none" }}
            onChange={(event) => {
              const input = event.currentTarget as HTMLInputElement;
              void importSystemFiles(input.files).finally(() => {
                input.value = "";
              });
            }}
          />
        </div>
        {importMessage != null ? (
          <p className="muted import-systems-note">{importMessage}</p>
        ) : null}
        {importProblems.length > 0 ? (
          <ul className="import-systems-problems">
            {importProblems.map((problem, index) => (
              <li key={`import-problem-${index}`}>{problem}</li>
            ))}
          </ul>
        ) : null}
        {userSystems.length > 0 ? (
          <ul className="import-systems-list">
            {userSystems.map((spec) => (
              <li key={`user-system-${spec.id}`}>
                <span>
                  <strong>{spec.id}</strong>
                  <span className="muted"> — {spec.label}</span>
                </span>
                <button
                  type="button"
                  className="ghost import-systems-remove"
                  title={`Remove ${spec.id}`}
                  onClick={() => removeUserSystem(spec.id)}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
      {editorOpen ? (
        <SystemEditor
          userSystems={userSystems}
          onCommitSystems={commitEditedSystems}
          onDropSystem={removeUserSystem}
          onClose={() => setEditorOpen(false)}
        />
      ) : null}
    </>
  );
}
