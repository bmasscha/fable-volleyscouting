/** Match / roster persistence. Plain JSON, crash-safe writes. */
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync, writeSync } from "node:fs";
import { dirname, join, parse } from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

import { MatchEvent, event_from_dict, event_to_dict } from "./events";
import { MatchConfig, Team, TeamKey, config_from_dict, config_to_dict, team_from_dict, team_to_dict } from "./models";

export const FILE_VERSION = 1;

function _atomic_write(path: string, text: string): void {
  /** Write via temp file + replace so a crash never corrupts the file. */
  mkdirSync(dirname(path), { recursive: true });
  let fd: number | null = null;
  let tmp = "";
  while (fd == null) {
    tmp = join(dirname(path), `${randomUUID()}.tmp`);
    try {
      fd = openSync(tmp, "wx");
    } catch (error: any) {
      if (error?.code !== "EEXIST") {
        throw error;
      }
    }
  }
  try {
    writeFileSync(fd, text, "utf8");
    fsyncSync(fd);
    closeSync(fd);
    fd = null;
    renameSync(tmp, path);
  } catch (error) {
    if (fd != null) {
      try {
        closeSync(fd);
      } catch {
        // pass
      }
    }
    try {
      unlinkSync(tmp);
    } catch {
      // pass
    }
    throw error;
  }
}

function _teams_to_dict(teams: Partial<Record<TeamKey, Team>>): Record<string, ReturnType<typeof team_to_dict>> {
  const out: Record<string, ReturnType<typeof team_to_dict>> = {};
  for (const key of Object.keys(teams) as TeamKey[]) {
    const team = teams[key];
    if (team != null) {
      out[key] = team_to_dict(team);
    }
  }
  return out;
}

function _teams_from_dict(d: Record<string, unknown>): Record<TeamKey, Team> {
  const teams = {} as Record<TeamKey, Team>;
  for (const [key, value] of Object.entries(d)) {
    teams[key as TeamKey] = team_from_dict(value);
  }
  return teams;
}

export function save_match(
  path: string,
  config: MatchConfig,
  teams: Partial<Record<TeamKey, Team>>,
  events: MatchEvent[],
): void {
  const data = {
    version: FILE_VERSION,
    config: config_to_dict(config),
    teams: _teams_to_dict(teams),
    events: events.map((event) => event_to_dict(event)),
  };
  _atomic_write(path, JSON.stringify(data, null, 1));
}

export function load_match(path: string): [MatchConfig, Record<TeamKey, Team>, MatchEvent[]] {
  /** Returns (config, teams, events). */
  const data = JSON.parse(readFileSync(path, "utf8")) as {
    config: Record<string, unknown>;
    teams: Record<string, unknown>;
    events: Record<string, unknown>[];
  };
  const config = config_from_dict(data.config);
  const teams = _teams_from_dict(data.teams);
  const events = data.events.map((d) => event_from_dict(d));
  return [config, teams, events];
}

// ---------------------------------------------------------- live event log
//
// Besides the full-snapshot autosave (save_match), the UI keeps an append-only
// .log.jsonl file: one JSON object per line, flushed and fsynced per event, so
// a crash or power loss never costs more than the line being written. The log
// is self-contained (header line carries config + teams) and replays undos, so
// a match can be rebuilt from the log alone.

export function log_path(match_path: string): string {
  /** Sidecar live-log path for a match file (match.json -> match.log.jsonl). */
  const p = parse(match_path);
  return join(p.dir, `${p.name}.log.jsonl`);
}

export class EventLogWriter {
  /** Append-only realtime event log. (Re)created to mirror the engine's
   * current event list, then appended to synchronously per event. */
  _path: string;
  _f: number;

  constructor(
    path: string,
    config: MatchConfig,
    teams: Partial<Record<TeamKey, Team>>,
    events: MatchEvent[] = [],
  ) {
    this._path = path;
    mkdirSync(dirname(this._path), { recursive: true });
    this._f = openSync(this._path, "w");
    this._write({
      type: "header",
      version: FILE_VERSION,
      config: config_to_dict(config),
      teams: _teams_to_dict(teams),
    });
    for (const event of events) {
      this.log_event(event);
    }
  }

  _write(obj: Record<string, unknown>): void {
    writeSync(this._f, `${JSON.stringify(obj)}\n`, undefined, "utf8");
    fsyncSync(this._f);
  }

  log_event(event: MatchEvent): void {
    this._write(event_to_dict(event));
  }

  log_undo(): void {
    this._write({ type: "undo" });
  }

  close(): void {
    try {
      closeSync(this._f);
    } catch {
      // pass
    }
  }
}

export function read_event_log(path: string): [MatchConfig, Record<TeamKey, Team>, MatchEvent[]] {
  /** Rebuild (config, teams, events) from a live log. Undo records pop the
   * last event; unparseable lines (e.g. truncated by a crash) are skipped. */
  let config: MatchConfig | null = null;
  let teams: Record<TeamKey, Team> | null = null;
  const events: MatchEvent[] = [];
  for (const raw_line of readFileSync(path, "utf8").split(/\r?\n/)) {
    const line = raw_line.trim();
    if (!line) {
      continue;
    }
    let d: any;
    try {
      d = JSON.parse(line);
    } catch {
      continue;
    }
    const kind = d.type;
    if (kind === "header") {
      config = config_from_dict(d.config);
      teams = _teams_from_dict(d.teams);
    } else if (kind === "undo") {
      if (events.length) {
        events.pop();
      }
    } else {
      try {
        events.push(event_from_dict(d));
      } catch {
        continue;
      }
    }
  }
  if (config == null || teams == null) {
    throw new Error(`${path}: no header record`);
  }
  return [config, teams, events];
}

export function load_match_with_log(
  path: string,
): [MatchConfig, Record<TeamKey, Team>, MatchEvent[], number] {
  /** Load a match, recovering from the live log when it is ahead of the
   * snapshot (crash between the last event and the last autosave).
   * Returns (config, teams, events, recovered_count). */
  const [config, teams, events] = load_match(path);
  const lp = log_path(path);
  if (existsSync(lp)) {
    try {
      const [lc, lt, levents] = read_event_log(lp);
      if (levents.length > events.length) {
        return [lc, lt, levents, levents.length - events.length];
      }
    } catch {
      return [config, teams, events, 0];
    }
  }
  return [config, teams, events, 0];
}

// ------------------------------------------------------------ roster library

export function rosters_dir(base: string | null = null): string {
  let d = base;
  if (d == null) {
    d = fileURLToPath(new URL("../../rosters", import.meta.url));
  }
  mkdirSync(d, { recursive: true });
  return d;
}

function _team_filename(team: Team): string {
  const safe = Array.from(team.name)
    .map((c) => (/^[\p{L}\p{N}]$/u.test(c) || " -_".includes(c) ? c : "_"))
    .join("")
    .trim();
  return `${safe || "team"}.json`;
}

export function save_team(team: Team, base: string | null = null): string {
  const path = join(rosters_dir(base), _team_filename(team));
  _atomic_write(path, JSON.stringify(team_to_dict(team), null, 1));
  return path;
}

export function load_teams(base: string | null = null): Team[] {
  const teams: Team[] = [];
  for (const name of readdirSync(rosters_dir(base)).filter((p) => p.endsWith(".json")).sort()) {
    try {
      teams.push(team_from_dict(JSON.parse(readFileSync(join(rosters_dir(base), name), "utf8"))));
    } catch {
      continue;
    }
  }
  return teams;
}

export function delete_team(team: Team, base: string | null = null): void {
  const path = join(rosters_dir(base), _team_filename(team));
  if (existsSync(path)) {
    unlinkSync(path);
  }
}
