import { useEffect, useMemo, useRef, useState } from "preact/hooks";

import { CourtSurface } from "./CourtSurface";
import {
  BLOCK_GRAB_RADIUS,
  BLOCK_NET_ZONE,
  BLOCK_OUT,
  COVERED,
  classify_block_deflection,
} from "./core/blocks";
import { MatchEngine, Phase } from "./core/engine";
import { MatchEvent, SetStartEvent } from "./core/events";
import {
  AWAY,
  HOME,
  Player,
  Rating,
  Team,
  TeamKey,
  TEAM_KEYS,
  other,
  role_abbrev,
  team_player,
} from "./core/models";
import {
  MatchSnapshot,
  clearAutosave,
  loadAutosave,
  loadRosterLibrary,
  loadUserSystems,
  saveAutosave,
  saveRosterLibrary,
  saveUserSystems,
} from "./browserStorage";
import {
  MatchSetupDraft,
  MatchSetupResult,
  POSITION_HINTS,
  POSITION_LABELS,
  ROLE_ORDER,
  addDraftPlayer,
  applyTeamSelection,
  buildMatchSetupResult,
  cloneTeam,
  createNewTeam,
  makeMatchSetupDraft,
  normalizedBoundedInteger,
  playerSummary,
  prepareTeamForSave,
  rotateSetupLineup,
  sortTeams,
} from "./setup";
import {
  DEFAULT_SYSTEM,
  SYSTEMS,
  SystemSpec,
  get_system,
  system_ids,
  system_note,
} from "./core/systems";
import { parse_import, refresh_registry } from "./core/user_systems";
import {
  CandidateSelection,
  PendingAttackState,
  buildCourtTokens,
  nearestPlayerId,
  recentCourtTrajectories,
  serveIsOut,
  teamRoles,
  trajectoriesExpired,
} from "./courtState";
import {
  benchEntries,
  benchSummary,
  cloneSetStartEvent,
  eligibleLineupPlayers,
  exchangeEventFor,
  rotateEditedSetLineup,
  validateEditedSetStart,
} from "./matchUi";
import { ReportPanel, TrajectoryPanel } from "./matchInsights";
import { SystemEditor } from "./SystemEditor";

const RATING_OPTIONS = [Rating.ERROR, Rating.POOR, Rating.GOOD, Rating.PERFECT] as const;

const RATING_CLASS: Record<Rating, string> = {
  [Rating.ERROR]: "error",
  [Rating.POOR]: "poor",
  [Rating.GOOD]: "good",
  [Rating.PERFECT]: "perfect",
};

// Per-phase hint text under the big rating buttons (mirrors ui/rating_bar.py CONTEXT_HINTS).
const CONTEXT_HINTS: Record<"serve" | "reception" | "attack" | "dig", Record<Rating, string>> = {
  serve: { [Rating.ERROR]: "fail", [Rating.POOR]: "not good", [Rating.GOOD]: "good", [Rating.PERFECT]: "point" },
  reception: { [Rating.ERROR]: "fail", [Rating.POOR]: "poor", [Rating.GOOD]: "good", [Rating.PERFECT]: "perfect" },
  attack: { [Rating.ERROR]: "error-out", [Rating.POOR]: "poor", [Rating.GOOD]: "good", [Rating.PERFECT]: "kill" },
  dig: { [Rating.ERROR]: "fail", [Rating.POOR]: "poor", [Rating.GOOD]: "good", [Rating.PERFECT]: "perfect" },
};

type Screen = "startup" | "setup" | "rosters" | "match";

interface PlayerOption {
  id: string;
  label: string;
}

function playerLabel(team: Team, playerId: string): string {
  const player = team_player(team, playerId);
  return player ? `#${player.number} ${player.name}` : playerId;
}

function teamLabel(teams: Record<TeamKey, Team>, teamKey: TeamKey): string {
  return teams[teamKey].name;
}

function phaseLabel(phase: string): string {
  return phase.replace(/_/g, " ");
}

function formatSavedAt(savedAt: number | null): string {
  return savedAt == null ? "just now" : new Date(savedAt).toLocaleString();
}

function stampEvent<T extends MatchEvent>(event: T): T {
  return { ...event, ts: Date.now() / 1000 };
}

function playerOptions(engine: MatchEngine, teamKey: TeamKey): PlayerOption[] {
  return engine.state.team[teamKey].lineup.map((playerId) => ({
    id: playerId,
    label: playerLabel(engine.teams[teamKey], playerId),
  }));
}

function statusTone(warnings: string[], alerts: string[]): "warning" | "ok" {
  return warnings.length > 0 || alerts.length > 0 ? "warning" : "ok";
}

function selectedPlayerText(engine: MatchEngine | null, candidate: CandidateSelection | null): string {
  if (engine == null || candidate == null) {
    return "Tap a player on the court.";
  }
  return `${teamLabel(engine.teams, candidate.teamKey)} · ${playerLabel(engine.teams[candidate.teamKey], candidate.playerId)}`;
}

function p1Text(engine: MatchEngine, teamKey: TeamKey): string {
  const playerId = engine.state.team[teamKey].lineup[0];
  return playerId == null ? "?" : playerLabel(engine.teams[teamKey], playerId);
}

function courtPrompt(
  engine: MatchEngine,
  candidate: CandidateSelection | null,
  pendingAttack: PendingAttackState | null,
  armedBench: CandidateSelection | null,
  interactionHint: string | null,
): string {
  if (interactionHint != null) {
    return interactionHint;
  }
  if (armedBench != null) {
    const benchPlayer = team_player(engine.teams[armedBench.teamKey], armedBench.playerId);
    return `Bench armed: tap an on-court ${teamLabel(engine.teams, armedBench.teamKey)} player to exchange with ${benchPlayer == null ? armedBench.playerId : `#${benchPlayer.number} ${benchPlayer.name}`}.`;
  }
  const state = engine.state;
  if (state.phase === Phase.AWAIT_SERVE) {
    const serverId = engine.expected_server();
    const server = serverId == null ? null : team_player(engine.teams[state.serving_team], serverId);
    return `Serve ${teamLabel(engine.teams, state.serving_team)} ${server == null ? "" : `#${server.number} ${server.name}`} by dragging the ball path.`;
  }
  if (state.phase === Phase.RECEPTION) {
    return `Rate reception for ${selectedPlayerText(engine, candidate)} or drag into the next attack.`;
  }
  if (state.phase === Phase.ATTACK) {
    return pendingAttack == null
      ? `Attack ${teamLabel(engine.teams, state.attacking_team ?? other(state.serving_team))}: drag a trajectory or tap an attacker.`
      : `Finalize attack for ${selectedPlayerText(engine, candidate)} with a rating.`;
  }
  if (state.phase === Phase.DEFENSE) {
    return pendingAttack == null
      ? `Rate the dig for ${selectedPlayerText(engine, candidate)} or drag a counter-attack.`
      : `Finalize counter-attack for ${selectedPlayerText(engine, candidate)} with a rating.`;
  }
  if (state.phase === Phase.SET_OVER) {
    return "Set finished. Start the next set when ready.";
  }
  if (state.phase === Phase.MATCH_OVER) {
    return "Match finished. Use reports or start the next match.";
  }
  return "";
}

interface TeamPanelProps {
  engine: MatchEngine;
  teamKey: TeamKey;
}

function TeamPanel({ engine, teamKey }: TeamPanelProps) {
  const team = engine.teams[teamKey];
  const teamState = engine.state.team[teamKey];
  return (
    <section className="team-panel" style={{ borderColor: team.color }}>
      <header>
        <div>
          <h3>{team.name}</h3>
          <p>
            Sets {engine.state.set_scores[teamKey]} · Points {engine.state.scores[teamKey]} · TO{" "}
            {teamState.timeouts}/2
          </p>
        </div>
        <span className={`serve-pill ${engine.state.serving_team === teamKey ? "active" : ""}`}>
          {engine.state.serving_team === teamKey ? "Serving" : "Receiving"}
        </span>
      </header>
      <ol className="lineup-list">
        {teamState.lineup.map((playerId, index) => (
          <li key={`${teamKey}-${playerId}-${index}`}>
            <span className="position-chip">{POSITION_LABELS[index]}</span>
            <span>{playerLabel(team, playerId)}</span>
          </li>
        ))}
      </ol>
      <p className="muted">
        Liberos:{" "}
        {teamState.liberos.length > 0
          ? teamState.liberos.map((playerId) => playerLabel(team, playerId)).join(", ")
          : "none"}
      </p>
    </section>
  );
}

interface BenchPanelProps {
  engine: MatchEngine;
  teamKey: TeamKey;
  armedBench: CandidateSelection | null;
  onArm: (teamKey: TeamKey, playerId: string) => void;
}

function BenchPanel({ engine, teamKey, armedBench, onArm }: BenchPanelProps) {
  const team = engine.teams[teamKey];
  const entries = benchEntries(engine, teamKey);
  const armedPlayerId = armedBench?.teamKey === teamKey ? armedBench.playerId : null;
  return (
    <section className="bench-panel" style={{ borderColor: team.color }}>
      <header>
        <div>
          <h3>{team.name} bench</h3>
          <p>{benchSummary(engine, teamKey)}</p>
        </div>
        {armedPlayerId != null ? <span className="serve-pill active">Armed</span> : null}
      </header>
      {entries.length === 0 ? (
        <p className="muted">No off-court players available.</p>
      ) : (
        <div className="bench-player-list">
          {entries.map((entry) => (
            <button
              key={`${teamKey}-${entry.playerId}`}
              type="button"
              className={`bench-player-button ${armedPlayerId === entry.playerId ? "active" : ""}`}
              style={{ background: entry.color }}
              onClick={() => onArm(teamKey, entry.playerId)}
            >
              <span className="bench-player-number">
                #{entry.number}
                {entry.badge !== "" ? ` · ${entry.badge}` : ""}
              </span>
              <span>{entry.name}</span>
            </button>
          ))}
        </div>
      )}
      <p className="muted">
        {armedPlayerId == null
          ? "Tap a bench player, then tap their on-court partner."
          : "Tap the same bench player again to cancel."}
      </p>
    </section>
  );
}

interface NextSetEditorProps {
  teams: Record<TeamKey, Team>;
  draft: SetStartEvent;
  validationError: string | null;
  onUpdateLineup: (teamKey: TeamKey, index: number, playerId: string) => void;
  onRotate: (teamKey: TeamKey, steps: number) => void;
  onServingTeamChange: (teamKey: TeamKey) => void;
  onLeftTeamChange: (teamKey: TeamKey) => void;
  onStart: () => void;
  onReset: () => void;
  onClose: () => void;
}

function NextSetEditor({
  teams,
  draft,
  validationError,
  onUpdateLineup,
  onRotate,
  onServingTeamChange,
  onLeftTeamChange,
  onStart,
  onReset,
  onClose,
}: NextSetEditorProps) {
  return (
    <section className="editor-shell">
      <div className="screen-header">
        <div>
          <h2>Set {draft.set_number} setup</h2>
          <p className="muted">Quick start uses the suggested lineups. Edit here to rotate or swap starters before the next whistle.</p>
        </div>
        <div className="button-row compact">
          <button type="button" className="ghost" onClick={onReset}>
            Reset
          </button>
          <button type="button" className="ghost" onClick={onClose}>
            Close
          </button>
          <button type="button" className="primary" onClick={onStart} disabled={validationError != null}>
            Start edited set
          </button>
        </div>
      </div>

      {validationError != null ? <div className="message-banner error">{validationError}</div> : null}

      <div className="team-grid">
        {TEAM_KEYS.map((teamKey) => {
          const team = teams[teamKey];
          const lineup = draft.lineups[teamKey];
          const liberos = draft.liberos[teamKey];
          const eligible = eligibleLineupPlayers(team, liberos);
          return (
            <section key={`next-set-${teamKey}`} className="team-panel setup-panel" style={{ borderColor: team.color }}>
              <header>
                <div>
                  <h3>{team.name}</h3>
                  <p className="muted">Starting lineup for set {draft.set_number}</p>
                </div>
              </header>

              <div className="lineup-editor">
                {POSITION_LABELS.map((position, index) => (
                  <label key={`${teamKey}-${position}`}>
                    {position} <span className="muted">{POSITION_HINTS[index]}</span>
                    <select
                      value={lineup[index] ?? ""}
                      onChange={(event) => onUpdateLineup(teamKey, index, (event.currentTarget as HTMLSelectElement).value)}
                    >
                      {eligible.map((player) => (
                        <option key={player.id} value={player.id}>
                          {playerSummary(player)}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>

              <div className="button-row compact">
                <button type="button" onClick={() => onRotate(teamKey, -1)}>
                  ⟲ rotate
                </button>
                <button type="button" onClick={() => onRotate(teamKey, 1)}>
                  rotate ⟳
                </button>
              </div>

              <p className="muted">
                Liberos: {liberos.length > 0 ? liberos.map((playerId) => playerLabel(team, playerId)).join(", ") : "none"}
              </p>
            </section>
          );
        })}
      </div>

      <div className="form-grid">
        <section className="control-card">
          <h3>First serve</h3>
          <div className="checkbox-list">
            {TEAM_KEYS.map((teamKey) => (
              <label key={`serve-${teamKey}`} className="checkbox-row">
                <input
                  type="radio"
                  name="next-set-serving-team"
                  checked={draft.serving_team === teamKey}
                  onChange={() => onServingTeamChange(teamKey)}
                />
                <span>{teamLabel(teams, teamKey)}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="control-card">
          <h3>Left side</h3>
          <div className="checkbox-list">
            {TEAM_KEYS.map((teamKey) => (
              <label key={`left-${teamKey}`} className="checkbox-row">
                <input
                  type="radio"
                  name="next-set-left-team"
                  checked={draft.left_team === teamKey}
                  onChange={() => onLeftTeamChange(teamKey)}
                />
                <span>{teamLabel(teams, teamKey)}</span>
              </label>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

interface RatingRowProps {
  onPick: (rating: Rating) => void;
}

function RatingRow({ onPick }: RatingRowProps) {
  return (
    <div className="rating-row">
      {RATING_OPTIONS.map((rating) => (
        <button key={rating} type="button" className="rating-button" onClick={() => onPick(rating)}>
          {rating}
        </button>
      ))}
    </div>
  );
}

interface StartupScreenProps {
  autosave: MatchSnapshot | null;
  rosterCount: number;
  storageError: string | null;
  onResume: () => void;
  onNewMatch: () => void;
  onManageTeams: () => void;
  onClearAutosave: () => void;
}

function StartupScreen({
  autosave,
  rosterCount,
  storageError,
  onResume,
  onNewMatch,
  onManageTeams,
  onClearAutosave,
}: StartupScreenProps) {
  return (
    <main className="shell">
      <section className="startup-card">
        <h1>Fable Scouter Tablet</h1>
        <p>Match setup now starts from a browser-side team library.</p>
        <p className="muted">{rosterCount} saved team(s) on this device.</p>
        {storageError != null ? <div className="message-banner error">{storageError}</div> : null}
        {autosave != null ? (
          <>
            <div className="resume-summary">
              <strong>
                {teamLabel(autosave.teams, HOME)} vs {teamLabel(autosave.teams, AWAY)}
              </strong>
              <span>
                {autosave.events.length} event(s) · autosaved {formatSavedAt(autosave.savedAt)}
              </span>
            </div>
            <div className="button-row">
              <button type="button" className="primary" onClick={onResume}>
                Resume
              </button>
              <button type="button" onClick={onNewMatch}>
                New match
              </button>
              <button type="button" onClick={onManageTeams}>
                Manage teams
              </button>
              <button type="button" className="ghost" onClick={onClearAutosave}>
                Clear autosave
              </button>
            </div>
          </>
        ) : (
          <div className="button-row">
            <button type="button" className="primary" onClick={onNewMatch}>
              New match
            </button>
            <button type="button" onClick={onManageTeams}>
              Manage teams
            </button>
          </div>
        )}
      </section>
    </main>
  );
}

interface RosterLibraryScreenProps {
  library: Team[];
  onSaveLibrary: (teams: Team[]) => boolean;
  onBack: () => void;
}

function RosterLibraryScreen({ library, onSaveLibrary, onBack }: RosterLibraryScreenProps) {
  const [selectedTeamName, setSelectedTeamName] = useState(library[0]?.name ?? "");
  const [draftTeam, setDraftTeam] = useState<Team | null>(library[0] != null ? cloneTeam(library[0]) : null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedTeam = useMemo(
    () => library.find((team) => team.name === selectedTeamName) ?? null,
    [library, selectedTeamName],
  );

  useEffect(() => {
    if (library.length === 0) {
      setSelectedTeamName("");
      setDraftTeam(null);
      return;
    }
    if (!library.some((team) => team.name === selectedTeamName)) {
      setSelectedTeamName(library[0]!.name);
      return;
    }
    setDraftTeam(selectedTeam != null ? cloneTeam(selectedTeam) : null);
  }, [library, selectedTeam, selectedTeamName]);

  const dirty = useMemo(() => {
    if (selectedTeam == null || draftTeam == null) {
      return false;
    }
    return JSON.stringify(selectedTeam) !== JSON.stringify(draftTeam);
  }, [draftTeam, selectedTeam]);

  function persist(teams: Team[]): boolean {
    const success = onSaveLibrary(sortTeams(teams));
    if (!success) {
      setError("Browser storage is unavailable, so changes could not be saved on this device.");
      setMessage(null);
      return false;
    }
    return true;
  }

  function saveDraft(team: Team, originalName: string | null): boolean {
    const result = prepareTeamForSave(team, library, originalName);
    if (result.error != null || result.team == null) {
      setError(result.error);
      setMessage(null);
      return false;
    }
    if (!persist([...library.filter((entry) => entry.name !== (originalName ?? "")), result.team])) {
      return false;
    }
    setSelectedTeamName(result.team.name);
    setMessage(`Saved ${result.team.name}.`);
    setError(null);
    return true;
  }

  function resolveLibraryBeforeNavigation(): Team[] | null {
    if (!dirty || draftTeam == null) {
      return library;
    }
    if (window.confirm(`Save changes to "${draftTeam.name || "this team"}" before leaving?`)) {
      const result = prepareTeamForSave(draftTeam, library, selectedTeam?.name ?? null);
      if (result.error != null || result.team == null) {
        setError(result.error);
        setMessage(null);
        return null;
      }
      const nextLibrary = sortTeams([
        ...library.filter((entry) => entry.name !== (selectedTeam?.name ?? "")),
        result.team,
      ]);
      if (!onSaveLibrary(nextLibrary)) {
        setError("Browser storage is unavailable, so changes could not be saved on this device.");
        setMessage(null);
        return null;
      }
      setSelectedTeamName(result.team.name);
      setMessage(`Saved ${result.team.name}.`);
      setError(null);
      return nextLibrary;
    }
    return window.confirm("Discard unsaved changes?") ? library : null;
  }

  function selectTeam(teamName: string): void {
    if (teamName === selectedTeamName) {
      return;
    }
    if (resolveLibraryBeforeNavigation() == null) {
      return;
    }
    setSelectedTeamName(teamName);
    setMessage(null);
    setError(null);
  }

  function leaveLibrary(): void {
    if (resolveLibraryBeforeNavigation() == null) {
      return;
    }
    onBack();
  }

  function createTeam(): void {
    const baseLibrary = resolveLibraryBeforeNavigation();
    if (baseLibrary == null) {
      return;
    }
    const nextTeam = createNewTeam(baseLibrary);
    if (!persist([...baseLibrary, nextTeam])) {
      return;
    }
    setSelectedTeamName(nextTeam.name);
    setMessage(`Created ${nextTeam.name}.`);
    setError(null);
  }

  function deleteTeam(): void {
    if (selectedTeam == null) {
      return;
    }
    if (!window.confirm(`Delete team "${selectedTeam.name}" from this device?`)) {
      return;
    }
    persist(library.filter((team) => team.name !== selectedTeam.name));
    setMessage(`Deleted ${selectedTeam.name}.`);
    setError(null);
  }

  function updateDraft(mutator: (team: Team) => Team): void {
    setDraftTeam((current) => (current == null ? current : mutator(current)));
  }

  function saveTeam(): void {
    if (draftTeam == null) {
      return;
    }
    saveDraft(draftTeam, selectedTeam?.name ?? null);
  }

  return (
    <main className="shell">
      <section className="editor-shell">
        <div className="screen-header">
          <div>
            <h1>Team library</h1>
            <p className="muted">Saved only in this browser. Manage rosters before starting a match.</p>
          </div>
          <div className="button-row compact">
            <button type="button" onClick={createTeam}>
              New team
            </button>
            <button type="button" className="ghost" onClick={leaveLibrary}>
              Back
            </button>
          </div>
        </div>

        {error != null ? <div className="message-banner error">{error}</div> : null}
        {message != null ? <div className="message-banner success">{message}</div> : null}

        <div className="editor-layout">
          <aside className="list-card">
            <h2>Saved teams</h2>
            <div className="team-library-list">
              {library.map((team) => (
                <button
                  key={team.name}
                  type="button"
                  className={`team-list-item ${selectedTeamName === team.name ? "active" : ""}`}
                  onClick={() => selectTeam(team.name)}
                >
                  <span className="color-dot" style={{ background: team.color }} />
                  <span>{team.name}</span>
                </button>
              ))}
              {library.length === 0 ? <p className="muted">No saved teams yet.</p> : null}
            </div>
          </aside>

          <section className="editor-card">
            {draftTeam == null ? (
              <div className="empty-state">
                <h2>No team selected</h2>
                <p className="muted">Create a team to start building a roster.</p>
              </div>
            ) : (
              <>
                <div className="editor-toolbar">
                  <div>
                    <h2>{draftTeam.name}</h2>
                    <p className="muted">{dirty ? "Unsaved changes" : "Saved"}</p>
                  </div>
                  <div className="button-row compact">
                    <button type="button" onClick={deleteTeam}>
                      Delete
                    </button>
                    <button type="button" className="primary" onClick={saveTeam}>
                      Save team
                    </button>
                  </div>
                </div>

                <div className="form-grid">
                  <label>
                    Team name
                    <input
                      value={draftTeam.name}
                      onInput={(event) => updateDraft((team) => ({
                        ...team,
                        name: (event.currentTarget as HTMLInputElement).value,
                      }))}
                    />
                  </label>
                  <label>
                    Team color
                    <div className="color-field">
                      <input
                        type="color"
                        value={draftTeam.color}
                        onInput={(event) => updateDraft((team) => ({
                          ...team,
                          color: (event.currentTarget as HTMLInputElement).value,
                        }))}
                      />
                      <span className="muted">{draftTeam.color}</span>
                    </div>
                  </label>
                </div>

                <div className="editor-toolbar">
                  <h3>Players</h3>
                  <button type="button" onClick={() => updateDraft((team) => addDraftPlayer(team))}>
                    Add player
                  </button>
                </div>

                <div className="player-table">
                  {draftTeam.players.map((player, index) => (
                    <div key={player.id} className="player-row">
                      <label>
                        No.
                        <input
                          type="number"
                          min="0"
                          max="99"
                          value={String(player.number)}
                          onInput={(event) => updateDraft((team) => ({
                            ...team,
                            players: team.players.map((entry, entryIndex) => (
                              entryIndex === index
                                ? {
                                  ...entry,
                                  number: normalizedBoundedInteger(
                                    Number((event.currentTarget as HTMLInputElement).value),
                                    0,
                                    99,
                                  ),
                                }
                                : entry
                            )),
                          }))}
                        />
                      </label>
                      <label>
                        Name
                        <input
                          value={player.name}
                          onInput={(event) => updateDraft((team) => ({
                            ...team,
                            players: team.players.map((entry, entryIndex) => (
                              entryIndex === index
                                ? { ...entry, name: (event.currentTarget as HTMLInputElement).value }
                                : entry
                            )),
                          }))}
                        />
                      </label>
                      <label>
                        Role
                        <select
                          value={player.role}
                          onChange={(event) => updateDraft((team) => ({
                            ...team,
                            players: team.players.map((entry, entryIndex) => (
                              entryIndex === index
                                ? { ...entry, role: (event.currentTarget as HTMLSelectElement).value as Player["role"] }
                                : entry
                            )),
                          }))}
                        >
                          {ROLE_ORDER.map((role) => (
                            <option key={role} value={role}>
                              {role} ({role_abbrev(role)})
                            </option>
                          ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        className="ghost danger"
                        onClick={() => updateDraft((team) => ({
                          ...team,
                          players: team.players.filter((_, entryIndex) => entryIndex !== index),
                        }))}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>

                {draftTeam.players.length === 0 ? (
                  <p className="muted">Add players, then save the team back to browser storage.</p>
                ) : null}
              </>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

interface MatchSetupScreenProps {
  library: Team[];
  draft: MatchSetupDraft;
  onDraftChange: (draft: MatchSetupDraft) => void;
  onManageTeams: () => void;
  onCancel: () => void;
  onStart: (result: MatchSetupResult) => void;
}

function MatchSetupScreen({
  library,
  draft,
  onDraftChange,
  onManageTeams,
  onCancel,
  onStart,
}: MatchSetupScreenProps) {
  const [error, setError] = useState<string | null>(null);
  const [userSystems, setUserSystems] = useState<SystemSpec[]>(() => loadUserSystems());
  const [importMessage, setImportMessage] = useState<string | null>(null);
  const [importProblems, setImportProblems] = useState<string[]>([]);
  const [editorOpen, setEditorOpen] = useState(false);
  const importInputRef = useRef<HTMLInputElement>(null);

  // The single write path shared by import, the editor's Save, and remove:
  // persist to storage, re-merge the registry (so the setup selects and the
  // stored-systems list below update immediately), and update local state.
  function persistUserSystems(nextList: SystemSpec[]): void {
    saveUserSystems(nextList);
    refresh_registry(nextList);
    setUserSystems(nextList);
  }

  const homeTeam = library.find((team) => team.name === draft.homeTeamName) ?? null;
  const awayTeam = library.find((team) => team.name === draft.awayTeamName) ?? null;

  useEffect(() => {
    setError(null);
  }, [draft, library]);

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
  // same path the import flow uses, so setup selects and the stored list
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
    // A team pointing at the removed id must not show a dangling value.
    let changed = false;
    const systems = { ...draft.systems };
    for (const teamKey of [HOME, AWAY] as const) {
      if (systems[teamKey] === systemId) {
        systems[teamKey] = DEFAULT_SYSTEM;
        changed = true;
      }
    }
    if (changed) {
      onDraftChange({ ...draft, systems });
    }
  }

  function updateLineup(teamKey: TeamKey, index: number, playerId: string): void {
    onDraftChange({
      ...draft,
      lineups: {
        ...draft.lineups,
        [teamKey]: draft.lineups[teamKey].map((entry, entryIndex) => (entryIndex === index ? playerId : entry)),
      },
    });
  }

  function rotateLineup(teamKey: TeamKey, steps: number): void {
    onDraftChange({
      ...draft,
      lineups: {
        ...draft.lineups,
        [teamKey]: rotateSetupLineup(draft.lineups[teamKey], steps),
      },
    });
  }

  function toggleLibero(teamKey: TeamKey, playerId: string, checked: boolean): void {
    const next = checked
      ? [...new Set([...draft.liberos[teamKey], playerId])]
      : draft.liberos[teamKey].filter((entry) => entry !== playerId);
    onDraftChange({
      ...draft,
      liberos: {
        ...draft.liberos,
        [teamKey]: next,
      },
    });
  }

  function startMatch(): void {
    const result = buildMatchSetupResult(draft, library);
    if (result.error != null || result.result == null) {
      setError(result.error);
      return;
    }
    onStart(result.result);
  }

  function renderTeamPanel(teamKey: TeamKey, label: string, team: Team | null, selectedName: string) {
    const lineup = draft.lineups[teamKey];
    const liberos = draft.liberos[teamKey];
    return (
      <section className="team-panel setup-panel" style={{ borderColor: team?.color ?? "#223743" }}>
        <header>
          <div>
            <h2>{label}</h2>
            <p className="muted">{team?.players.length ?? 0} rostered player(s)</p>
          </div>
        </header>

        <label>
          Saved team
          <select
            value={selectedName}
            onChange={(event) => onDraftChange(applyTeamSelection(
              draft,
              teamKey,
              (event.currentTarget as HTMLSelectElement).value,
              library,
            ))}
          >
            <option value="">— select —</option>
            {library.map((entry) => (
              <option key={`${teamKey}-${entry.name}`} value={entry.name}>
                {entry.name}
              </option>
            ))}
          </select>
        </label>

        <label>
          Playing system
          <select
            value={draft.systems[teamKey]}
            title={SYSTEMS[draft.systems[teamKey]]?.description}
            onChange={(event) => onDraftChange({
              ...draft,
              systems: {
                ...draft.systems,
                [teamKey]: (event.currentTarget as HTMLSelectElement).value,
              },
            })}
          >
            {system_ids().map((systemId) => (
              <option key={`${teamKey}-system-${systemId}`} value={systemId} title={SYSTEMS[systemId].description}>
                {SYSTEMS[systemId].label}
              </option>
            ))}
          </select>
        </label>

        <div className="lineup-editor">
          {POSITION_LABELS.map((position, index) => (
            <label key={`${teamKey}-${position}`}>
              {position} <span className="muted">{POSITION_HINTS[index]}</span>
              <select
                value={lineup[index] ?? ""}
                onChange={(event) => updateLineup(teamKey, index, (event.currentTarget as HTMLSelectElement).value)}
                disabled={team == null}
              >
                <option value="">— select —</option>
                {(team?.players ?? []).map((player) => (
                  <option key={player.id} value={player.id}>
                    {playerSummary(player)}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>

        <div className="button-row compact">
          <button type="button" onClick={() => rotateLineup(teamKey, -1)} disabled={team == null}>
            ⟲ rotate
          </button>
          <button type="button" onClick={() => rotateLineup(teamKey, 1)} disabled={team == null}>
            rotate ⟳
          </button>
        </div>

        <div className="libero-box">
          <h3>Liberos</h3>
          {(team?.players ?? []).length === 0 ? (
            <p className="muted">Select a team to configure libero(s).</p>
          ) : (
            <div className="checkbox-list">
              {team!.players.map((player) => (
                <label key={`${teamKey}-libero-${player.id}`} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={liberos.includes(player.id)}
                    onChange={(event) => toggleLibero(
                      teamKey,
                      player.id,
                      (event.currentTarget as HTMLInputElement).checked,
                    )}
                  />
                  <span>{playerSummary(player)}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      </section>
    );
  }

  return (
    <main className="shell">
      <section className="editor-shell">
        <div className="screen-header">
          <div>
            <h1>New match setup</h1>
            <p className="muted">Choose teams, lineups, liberos, serving order, sides, and match format.</p>
          </div>
          <div className="button-row compact">
            <button type="button" onClick={onManageTeams}>
              Edit team library
            </button>
            <button type="button" className="ghost" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </div>

        {error != null ? <div className="message-banner error">{error}</div> : null}

        {library.length === 0 ? (
          <section className="startup-card">
            <h2>No saved teams yet</h2>
            <p className="muted">Create at least two teams before starting a match.</p>
            <div className="button-row compact">
              <button type="button" className="primary" onClick={onManageTeams}>
                Create teams
              </button>
              <button type="button" className="ghost" onClick={onCancel}>
                Back
              </button>
            </div>
          </section>
        ) : (
          <>
            <section className="team-grid">
              {renderTeamPanel(HOME, "Home team", homeTeam, draft.homeTeamName)}
              {renderTeamPanel(AWAY, "Away team", awayTeam, draft.awayTeamName)}
            </section>

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

            <section className="controls-grid">
              <article className="control-card">
                <h2>First serving team</h2>
                <label className="checkbox-row">
                  <input
                    type="radio"
                    name="serving-team"
                    checked={draft.servingTeam === HOME}
                    onChange={() => onDraftChange({ ...draft, servingTeam: HOME })}
                  />
                  <span>Home</span>
                </label>
                <label className="checkbox-row">
                  <input
                    type="radio"
                    name="serving-team"
                    checked={draft.servingTeam === AWAY}
                    onChange={() => onDraftChange({ ...draft, servingTeam: AWAY })}
                  />
                  <span>Away</span>
                </label>
              </article>

              <article className="control-card">
                <h2>Starting on the left side</h2>
                <label className="checkbox-row">
                  <input
                    type="radio"
                    name="left-team"
                    checked={draft.leftTeam === HOME}
                    onChange={() => onDraftChange({ ...draft, leftTeam: HOME })}
                  />
                  <span>Home</span>
                </label>
                <label className="checkbox-row">
                  <input
                    type="radio"
                    name="left-team"
                    checked={draft.leftTeam === AWAY}
                    onChange={() => onDraftChange({ ...draft, leftTeam: AWAY })}
                  />
                  <span>Away</span>
                </label>
              </article>

              <article className="control-card">
                <h2>Match format</h2>
                <label className="checkbox-row">
                  <input
                    type="radio"
                    name="sets-to-win"
                    checked={draft.setsToWin === 3}
                    onChange={() => onDraftChange({ ...draft, setsToWin: 3 })}
                  />
                  <span>Best of 5</span>
                </label>
                <label className="checkbox-row">
                  <input
                    type="radio"
                    name="sets-to-win"
                    checked={draft.setsToWin === 2}
                    onChange={() => onDraftChange({ ...draft, setsToWin: 2 })}
                  />
                  <span>Best of 3</span>
                </label>
                <label>
                  Points per set
                  <input
                    type="number"
                    min="5"
                    max="99"
                    value={String(draft.pointsPerSet)}
                    onInput={(event) => onDraftChange({
                      ...draft,
                      pointsPerSet: normalizedBoundedInteger(
                        Number((event.currentTarget as HTMLInputElement).value),
                        5,
                        99,
                      ),
                    })}
                  />
                </label>
                <label>
                  Deciding set points
                  <input
                    type="number"
                    min="5"
                    max="99"
                    value={String(draft.pointsDecidingSet)}
                    onInput={(event) => onDraftChange({
                      ...draft,
                      pointsDecidingSet: normalizedBoundedInteger(
                        Number((event.currentTarget as HTMLInputElement).value),
                        5,
                        99,
                      ),
                    })}
                  />
                </label>
                <label>
                  Substitutions per set
                  <input
                    type="number"
                    min="0"
                    max="20"
                    value={String(draft.subsPerSet)}
                    onInput={(event) => onDraftChange({
                      ...draft,
                      subsPerSet: normalizedBoundedInteger(
                        Number((event.currentTarget as HTMLInputElement).value),
                        0,
                        20,
                      ),
                    })}
                  />
                </label>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={draft.liberoMayServe}
                    onChange={(event) => onDraftChange({
                      ...draft,
                      liberoMayServe: (event.currentTarget as HTMLInputElement).checked,
                    })}
                  />
                  <span>Libero may serve</span>
                </label>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={draft.autoLibero}
                    onChange={(event) => onDraftChange({
                      ...draft,
                      autoLibero: (event.currentTarget as HTMLInputElement).checked,
                    })}
                  />
                  <span>Automatic libero exchange</span>
                </label>
                <label className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={draft.switchSides}
                    onChange={(event) => onDraftChange({
                      ...draft,
                      switchSides: (event.currentTarget as HTMLInputElement).checked,
                    })}
                  />
                  <span>Teams switch sides between sets (off for VNL)</span>
                </label>
              </article>
            </section>

            <div className="button-row">
              <button type="button" className="ghost" onClick={onCancel}>
                Back
              </button>
              <button type="button" className="primary" onClick={startMatch}>
                Start match
              </button>
            </div>
          </>
        )}
      </section>
      {editorOpen ? (
        <SystemEditor
          userSystems={userSystems}
          onCommitSystems={commitEditedSystems}
          onDropSystem={removeUserSystem}
          onClose={() => setEditorOpen(false)}
        />
      ) : null}
    </main>
  );
}

export function App() {
  const [session, setSession] = useState<MatchSnapshot | null>(null);
  const [autosave, setAutosave] = useState<MatchSnapshot | null>(null);
  const [rosterLibrary, setRosterLibrary] = useState<Team[]>([]);
  const [screen, setScreen] = useState<Screen>("startup");
  const [libraryReturnScreen, setLibraryReturnScreen] = useState<"startup" | "setup">("startup");
  const [setupDraft, setSetupDraft] = useState<MatchSetupDraft | null>(null);
  const [storageError, setStorageError] = useState<string | null>(null);

  const [formationsEnabled, setFormationsEnabled] = useState(true);
  const [showRolesEnabled, setShowRolesEnabled] = useState(false);
  const [candidate, setCandidate] = useState<CandidateSelection | null>(null);
  const [pendingAttack, setPendingAttack] = useState<PendingAttackState | null>(null);
  const [armedBench, setArmedBench] = useState<CandidateSelection | null>(null);
  const [interactionHint, setInteractionHint] = useState<string | null>(null);
  const [editingNextSet, setEditingNextSet] = useState(false);
  const [nextSetDraft, setNextSetDraft] = useState<SetStartEvent | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [trajectoryOpen, setTrajectoryOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);

  const [servePlayer, setServePlayer] = useState("");
  const [receptionPlayer, setReceptionPlayer] = useState("");
  const [attackPlayer, setAttackPlayer] = useState("");
  const [digPlayer, setDigPlayer] = useState("");
  const [rallyReason, setRallyReason] = useState("");

  useEffect(() => {
    const savedAutosave = loadAutosave();
    const savedLibrary = loadRosterLibrary();
    setAutosave(savedAutosave);
    setRosterLibrary(savedLibrary);
    setSetupDraft(makeMatchSetupDraft(savedLibrary));
  }, []);

  useEffect(() => {
    setSetupDraft((current) => makeMatchSetupDraft(rosterLibrary, current));
  }, [rosterLibrary]);

  const engine = useMemo(() => {
    if (session == null) {
      return null;
    }
    const nextEngine = new MatchEngine(session.config, session.teams);
    nextEngine.load_events(session.events);
    return nextEngine;
  }, [session]);

  const currentWarnings = session?.lastWarnings ?? [];
  const currentAlerts = useMemo(() => {
    if (engine == null) {
      return [];
    }
    const alerts = engine.pending_alerts();
    if (formationsEnabled) {
      for (const teamKey of TEAM_KEYS) {
        const spec = get_system(engine.config.systems[teamKey]);
        const note = system_note(spec, teamRoles(engine, teamKey));
        if (note != null) {
          alerts.push(`${engine.teams[teamKey].name}: ${note}`);
        }
      }
    }
    return alerts;
  }, [engine, formationsEnabled]);
  const suggestedNextSet = engine?.suggest_next_set_start() ?? null;
  // fixed courts (VNL): the engine suggestion flips sides between sets;
  // keep the current assignment instead. The scouter can still override
  // either way via the swap-sides button / next-set editor.
  const nextSet = suggestedNextSet == null || engine == null || (session?.switchSides ?? true)
    ? suggestedNextSet
    : { ...suggestedNextSet, left_team: engine.state.left_team };
  const servingTeam = engine?.state.serving_team ?? HOME;
  const receivingTeam = engine == null ? AWAY : other(engine.state.serving_team);
  const attackingTeam = engine?.state.attacking_team ?? receivingTeam;
  const diggingTeam = engine?.state.attacking_team == null ? receivingTeam : other(engine.state.attacking_team);
  const leftTeam = engine?.state.left_team ?? HOME;
  const rightTeam = engine == null ? AWAY : other(engine.state.left_team);

  useEffect(() => {
    if (nextSet == null) {
      setEditingNextSet(false);
      setNextSetDraft(null);
      return;
    }
    setNextSetDraft(cloneSetStartEvent(nextSet));
  }, [session?.events.length, nextSet?.set_number, engine?.state.phase]);

  const serveOptions = useMemo(() => (
    engine == null ? [] : playerOptions(engine, servingTeam)
  ), [engine, servingTeam]);
  const receptionOptions = useMemo(() => (
    engine == null ? [] : playerOptions(engine, receivingTeam)
  ), [engine, receivingTeam]);
  const attackOptions = useMemo(() => (
    engine == null ? [] : playerOptions(engine, attackingTeam)
  ), [engine, attackingTeam]);
  const digOptions = useMemo(() => (
    engine == null ? [] : playerOptions(engine, diggingTeam)
  ), [engine, diggingTeam]);
  const pendingAttackOptions = useMemo(() => (
    engine == null || pendingAttack == null ? [] : playerOptions(engine, pendingAttack.teamKey)
  ), [engine, pendingAttack]);
  const courtTokens = useMemo(() => (
    engine == null ? [] : buildCourtTokens(engine, candidate, formationsEnabled, showRolesEnabled, pendingAttack)
  ), [candidate, engine, formationsEnabled, showRolesEnabled, pendingAttack]);
  const recentTrajectories = useMemo(() => {
    if (session == null) {
      return [];
    }
    const trajectories = recentCourtTrajectories(session.events);
    if (pendingAttack?.trajectory != null) {
      trajectories.push({
        kind: "attack",
        trajectory: pendingAttack.trajectory,
        opacity: 1,
      });
    }
    return trajectories;
  }, [session, pendingAttack]);
  const rallyTrajectoriesExpired = engine != null && trajectoriesExpired(engine);

  useEffect(() => {
    const fallback = engine?.expected_server() ?? serveOptions[0]?.id ?? "";
    setServePlayer((current) => (serveOptions.some((option) => option.id === current) ? current : fallback));
  }, [engine, serveOptions]);

  useEffect(() => {
    const fallback = receptionOptions[0]?.id ?? "";
    setReceptionPlayer((current) => (
      receptionOptions.some((option) => option.id === current) ? current : fallback
    ));
  }, [receptionOptions]);

  useEffect(() => {
    const fallback = attackOptions[0]?.id ?? "";
    setAttackPlayer((current) => (attackOptions.some((option) => option.id === current) ? current : fallback));
  }, [attackOptions]);

  useEffect(() => {
    const fallback = digOptions[0]?.id ?? "";
    setDigPlayer((current) => (digOptions.some((option) => option.id === current) ? current : fallback));
  }, [digOptions]);

  function commit(nextSession: MatchSnapshot): void {
    setSession(nextSession);
    setAutosave(nextSession);
    if (!saveAutosave(nextSession)) {
      setStorageError("Autosave could not be written in this browser. Keep the tab open until storage works again.");
    } else {
      setStorageError(null);
    }
  }

  function persistRosterLibrary(nextLibrary: Team[]): boolean {
    const sorted = sortTeams(nextLibrary);
    if (!saveRosterLibrary(sorted)) {
      setStorageError("Team library changes could not be saved in this browser.");
      return false;
    }
    setStorageError(null);
    setRosterLibrary(sorted);
    return true;
  }

  function clearCourtTransientState(): void {
    setCandidate(null);
    setPendingAttack(null);
    setInteractionHint(null);
  }

  function resetTransientInputs(): void {
    clearCourtTransientState();
    setArmedBench(null);
    setEditingNextSet(false);
    setNextSetDraft(null);
    setReportOpen(false);
    setTrajectoryOpen(false);
    setToolsOpen(false);
    setRallyReason("");
  }

  function openSetup(): void {
    setSetupDraft((current) => makeMatchSetupDraft(rosterLibrary, current));
    setScreen("setup");
  }

  function openRosterLibrary(): void {
    setLibraryReturnScreen(screen === "setup" ? "setup" : "startup");
    setScreen("rosters");
  }

  function startConfiguredMatch(result: MatchSetupResult): void {
    commit({
      config: result.config,
      teams: result.teams,
      events: [stampEvent(result.setStartEvent)],
      lastWarnings: [],
      switchSides: result.switchSides,
      savedAt: Date.now(),
    });
    resetTransientInputs();
    setScreen("match");
  }

  function appendEvent(event: MatchEvent | MatchEvent[]): MatchEngine | null {
    if (session == null) {
      return null;
    }
    const inputs = Array.isArray(event) ? event : [event];
    if (inputs.length === 0) {
      return null;
    }
    const preview = new MatchEngine(session.config, session.teams);
    preview.load_events(session.events);
    // a gesture may log more than one event at once (e.g. a reception and the
    // blocked attack drawn out of it); warnings reflect the last, decisive one
    const appended: MatchEvent[] = [];
    let warnings: string[] = [];
    for (const input of inputs) {
      const stamped = stampEvent(input);
      warnings = preview.append(stamped);
      appended.push(stamped);
    }
    // with config.auto_libero the app enters the engine-proposed libero
    // exchanges (forced front-row exits, learned serve-receive
    // re-entries) right after the user's event; undoLast removes them
    // together with the event that triggered them
    const autoNotices: string[] = [];
    for (let i = 0; i < 6; i++) {
      const auto = preview.next_auto_libero_swap();
      if (auto == null) {
        break;
      }
      const exiting = preview.state.team[auto.team].lineup.includes(auto.libero_id);
      const stampedAuto = stampEvent(auto);
      preview.append(stampedAuto);
      appended.push(stampedAuto);
      const lib = team_player(session.teams[auto.team], auto.libero_id);
      const par = team_player(session.teams[auto.team], auto.partner_id);
      const lib_n = lib ? `#${lib.number}` : "?";
      const par_n = par ? `#${par.number}` : "?";
      autoNotices.push(exiting
        ? `auto: ${par_n} back in for libero ${lib_n}`
        : `auto: libero ${lib_n} in for ${par_n}`);
    }
    commit({
      ...session,
      events: [...session.events, ...appended],
      lastWarnings: warnings.length ? warnings : autoNotices,
      savedAt: Date.now(),
    });
    setInteractionHint(null);
    if (
      preview.state.phase === Phase.AWAIT_SERVE
      || preview.state.phase === Phase.SET_OVER
      || preview.state.phase === Phase.MATCH_OVER
    ) {
      setCandidate(null);
      setPendingAttack(null);
    }
    return preview;
  }

  function undoLast(): void {
    if (session == null || session.events.length <= 1) {
      return;
    }
    clearCourtTransientState();
    setArmedBench(null);
    setEditingNextSet(false);
    // auto libero swaps were entered by the app, not the scouter: one
    // undo removes them together with the event that caused them
    let events = session.events;
    while (events.length > 1) {
      const last = events[events.length - 1];
      events = events.slice(0, -1);
      if (!(last.type === "libero_swap" && last.auto === true)) {
        break;
      }
    }
    commit({
      ...session,
      events,
      lastWarnings: [],
      savedAt: Date.now(),
    });
  }

  function applyManualScore(teamKey: TeamKey, sign: 1 | -1): void {
    appendEvent({ type: "manual_score", team: teamKey, delta: sign });
  }

  function chooseCandidate(teamKey: TeamKey, playerId: string): void {
    setCandidate({ teamKey, playerId });
    setInteractionHint(null);
    if (teamKey === servingTeam) {
      setServePlayer(playerId);
    }
    if (teamKey === receivingTeam) {
      setReceptionPlayer(playerId);
    }
    if (teamKey === attackingTeam) {
      setAttackPlayer(playerId);
    }
    if (teamKey === diggingTeam) {
      setDigPlayer(playerId);
    }
    setPendingAttack((current) => (
      current != null && current.teamKey === teamKey ? { ...current, playerId } : current
    ));
  }

  function nearestOnEngine(sourceEngine: MatchEngine, teamKey: TeamKey, x: number, y: number): string | null {
    return nearestPlayerId(sourceEngine, teamKey, x, y, formationsEnabled)
      ?? sourceEngine.state.team[teamKey].lineup[0]
      ?? null;
  }

  function primePendingAttack(
    sourceEngine: MatchEngine,
    teamKey: TeamKey,
    trajectory: [number, number, number, number],
    preferCurrentCandidate = true,
  ): void {
    const attacker = preferCurrentCandidate && candidate?.teamKey === teamKey
      ? candidate.playerId
      : nearestOnEngine(sourceEngine, teamKey, trajectory[0], trajectory[1]);
    if (attacker == null) {
      setInteractionHint("No on-court attacker is available.");
      return;
    }
    setCandidate({ teamKey, playerId: attacker });
    setPendingAttack({ teamKey, playerId: attacker, trajectory });
    setAttackPlayer(attacker);
    setInteractionHint(null);
  }

  function primeDigger(sourceEngine: MatchEngine, teamKey: TeamKey, trajectory: [number, number, number, number] | null): void {
    const fallback = sourceEngine.state.team[teamKey].lineup[5] ?? sourceEngine.state.team[teamKey].lineup[0] ?? null;
    const digger = trajectory == null
      ? fallback
      : nearestPlayerId(sourceEngine, teamKey, trajectory[2], trajectory[3], formationsEnabled) ?? fallback;
    if (digger == null) {
      setCandidate(null);
      return;
    }
    setCandidate({ teamKey, playerId: digger });
    setDigPlayer(digger);
  }

  function rerateLastServe(rating: Rating): void {
    if (session == null || engine == null || session.events.length === 0) {
      return;
    }
    const last = session.events[session.events.length - 1];
    if (last.type !== "serve") {
      setInteractionHint("Serve rating can only change right after the serve.");
      return;
    }
    const revised = { ...last, rating };
    const baseEvents = session.events.slice(0, -1);
    const preview = new MatchEngine(session.config, session.teams);
    preview.load_events(baseEvents);
    const warnings = preview.append(revised);
    commit({
      ...session,
      events: [...baseEvents, revised],
      lastWarnings: warnings,
      savedAt: Date.now(),
    });
    setPendingAttack(null);
    setInteractionHint(null);
    if (preview.state.phase === Phase.RECEPTION && revised.trajectory != null) {
      const receiver = nearestOnEngine(preview, other(revised.team), revised.trajectory[2], revised.trajectory[3]);
      if (receiver != null) {
        setCandidate({ teamKey: other(revised.team), playerId: receiver });
        setReceptionPlayer(receiver);
      }
      return;
    }
    setCandidate(null);
  }

  function handleCourtTrajectory(
    x1: number,
    y1: number,
    x2: number,
    y2: number,
    vertex: [number, number] | null = null,
  ): void {
    if (engine == null) {
      return;
    }

    // Single-stroke block gesture: one continuous drag that bends at the net
    // is the attack arrow (start -> block touch) and the deflection (block
    // touch -> landing) in one motion. The apex sitting in the net zone is what
    // marks it as a block; anywhere else the bend is ignored and the drag reads
    // as a straight trajectory. Auto-finalizes the attack -- no rating tap.
    // Skipped while an attack is pending: that follow-up drag belongs to the
    // two-stroke deflection path below.
    if (pendingAttack == null && vertex != null && Math.abs(vertex[0]) <= BLOCK_NET_ZONE) {
      const phase = engine.state.phase;
      const team = phase === Phase.ATTACK
        ? attackingTeam
        : phase === Phase.DEFENSE
          ? diggingTeam
          : phase === Phase.RECEPTION
            ? receivingTeam
            : null;
      if (team != null) {
        const attacker = candidate?.teamKey === team
          ? candidate.playerId
          : nearestOnEngine(engine, team, x1, y1);
        if (attacker != null) {
          const landing: [number, number, number, number] = [
            Number(x1.toFixed(2)), Number(y1.toFixed(2)),
            Number(x2.toFixed(2)), Number(y2.toFixed(2)),
          ];
          const touch: [number, number] = [
            Number(vertex[0].toFixed(2)), Number(vertex[1].toFixed(2)),
          ];
          const kind = classify_block_deflection(engine.side_of(team), x2, y2);
          const rating = kind === BLOCK_OUT
            ? Rating.PERFECT
            : kind === COVERED ? Rating.POOR : Rating.GOOD;
          // out of reception the drag doubles as the reception, so log it
          // first (rated good) before the blocked attack it feeds
          const priorEvents: MatchEvent[] = phase === Phase.RECEPTION
            ? [{ type: "reception", team: receivingTeam, player_id: attacker, rating: Rating.GOOD }]
            : [];
          const preview = appendEvent([
            ...priorEvents,
            {
              type: "attack",
              team,
              player_id: attacker,
              rating,
              trajectory: landing,
              block_touch: touch,
            },
          ]);
          setPendingAttack(null);
          if (preview?.state.phase === Phase.DEFENSE) {
            primeDigger(preview, other(preview.state.attacking_team!), landing);
          } else {
            setCandidate(null);
          }
          return;
        }
      }
    }

    // Two-stroke block gesture: a follow-up drag that starts near a pending
    // attack's arrow tip (which sits at the net) is the block deflection.
    // It auto-finalizes the attack -- no rating tap.
    if (pendingAttack != null) {
      const [, , px, py] = pendingAttack.trajectory;
      const isDeflection = Math.abs(px) <= BLOCK_NET_ZONE
        && Math.hypot(x1 - px, y1 - py) <= BLOCK_GRAB_RADIUS;
      if (isDeflection) {
        const team = pendingAttack.teamKey;
        const t = pendingAttack.trajectory;
        const landing: [number, number, number, number] = [
          t[0], t[1], Number(x2.toFixed(2)), Number(y2.toFixed(2)),
        ];
        const kind = classify_block_deflection(engine.side_of(team), x2, y2);
        const rating = kind === BLOCK_OUT
          ? Rating.PERFECT
          : kind === COVERED ? Rating.POOR : Rating.GOOD;
        const preview = appendEvent({
          type: "attack",
          team,
          player_id: pendingAttack.playerId,
          rating,
          trajectory: landing,
          block_touch: [px, py],
        });
        setPendingAttack(null);
        if (preview?.state.phase === Phase.DEFENSE) {
          // whoever the ball now travels toward digs next -- the covering
          // (attacking) team itself when the deflection was covered.
          primeDigger(preview, other(preview.state.attacking_team!), landing);
        } else {
          setCandidate(null);
        }
        return;
      }

      // Not a deflection: the scouter drew the next attack without scoring the
      // previous one. Finalize it with the default '+' (in play) so a fast
      // rally can be charted continuously, then let this drag start the next
      // (counter-)attack -- mirroring a tapped '+' followed by a fresh drag.
      const finished = pendingAttack;
      const preview = appendEvent({
        type: "attack",
        team: finished.teamKey,
        player_id: finished.playerId,
        rating: Rating.GOOD,
        trajectory: finished.trajectory,
      });
      setPendingAttack(null);
      const newTrajectory: [number, number, number, number] = [
        Number(x1.toFixed(2)), Number(y1.toFixed(2)),
        Number(x2.toFixed(2)), Number(y2.toFixed(2)),
      ];
      if (preview != null && preview.state.phase === Phase.DEFENSE) {
        // a GOOD attack in play hands the ball to the other team; this drag
        // is their counter-attack. Its attacker is whoever the line starts
        // from (nearest the drag origin), not the digger by the landing.
        primePendingAttack(preview, other(preview.state.attacking_team!), newTrajectory);
      } else {
        setCandidate(null);
      }
      return;
    }

    const trajectory: [number, number, number, number] = [
      Number(x1.toFixed(2)),
      Number(y1.toFixed(2)),
      Number(x2.toFixed(2)),
      Number(y2.toFixed(2)),
    ];

    if (engine.state.phase === Phase.AWAIT_SERVE) {
      const serverId = servePlayer || engine.expected_server() || serveOptions[0]?.id || "";
      if (serverId === "") {
        setInteractionHint("Select the server before dragging the serve.");
        return;
      }
      const preview = appendEvent({
        type: "serve",
        team: servingTeam,
        player_id: serverId,
        rating: serveIsOut(engine, servingTeam, x2, y2) ? Rating.ERROR : Rating.GOOD,
        trajectory,
      });
      if (preview?.state.phase === Phase.RECEPTION) {
        const receiver = nearestOnEngine(preview, other(servingTeam), x2, y2);
        if (receiver != null) {
          setCandidate({ teamKey: other(servingTeam), playerId: receiver });
          setReceptionPlayer(receiver);
        }
      }
      return;
    }

    if (engine.state.phase === Phase.RECEPTION) {
      const receiver = candidate?.teamKey === receivingTeam
        ? candidate.playerId
        : nearestOnEngine(engine, receivingTeam, x1, y1) || "";
      if (receiver === "") {
        setInteractionHint("Tap the receiver first, or choose one from the list.");
        return;
      }
      const preview = appendEvent({
        type: "reception",
        team: receivingTeam,
        player_id: receiver,
        rating: Rating.GOOD,
      });
      setReceptionPlayer(receiver);
      if (preview != null) {
        setCandidate(null);
        setPendingAttack(null);
        primePendingAttack(preview, receivingTeam, trajectory, false);
      }
      return;
    }

    if (engine.state.phase === Phase.ATTACK) {
      primePendingAttack(engine, attackingTeam, trajectory);
      return;
    }

    if (engine.state.phase === Phase.DEFENSE) {
      primePendingAttack(engine, diggingTeam, trajectory);
    }
  }

  function handleRatingPick(rating: Rating): void {
    if (engine == null) {
      return;
    }

    if (pendingAttack != null) {
      const preview = appendEvent({
        type: "attack",
        team: pendingAttack.teamKey,
        player_id: pendingAttack.playerId,
        rating,
        trajectory: pendingAttack.trajectory,
      });
      setPendingAttack(null);
      if (preview?.state.phase === Phase.DEFENSE) {
        primeDigger(preview, other(pendingAttack.teamKey), pendingAttack.trajectory);
      } else {
        setCandidate(null);
      }
      return;
    }

    if (engine.state.phase === Phase.RECEPTION) {
      if (candidate?.teamKey !== receivingTeam) {
        setInteractionHint("Tap the receiver first, or choose one from the list.");
        return;
      }
      const receiver = candidate.playerId;
      appendEvent({
        type: "reception",
        team: receivingTeam,
        player_id: receiver,
        rating,
      });
      setCandidate(null);
      return;
    }

    if (engine.state.phase === Phase.ATTACK) {
      if (candidate?.teamKey !== attackingTeam) {
        setInteractionHint("Drag the attack or tap the attacker first.");
        return;
      }
      const attacker = candidate.playerId;
      const preview = appendEvent({
        type: "attack",
        team: attackingTeam,
        player_id: attacker,
        rating,
      });
      if (preview?.state.phase === Phase.DEFENSE) {
        primeDigger(preview, other(attackingTeam), null);
      } else {
        setCandidate(null);
      }
      return;
    }

    if (engine.state.phase === Phase.DEFENSE) {
      if (candidate?.teamKey !== diggingTeam) {
        setInteractionHint("Tap the defender first, or drag the counter-attack.");
        return;
      }
      const digger = candidate.playerId;
      appendEvent({
        type: "dig",
        team: diggingTeam,
        player_id: digger,
        rating,
      });
      setCandidate(null);
      return;
    }

    setInteractionHint("Drag the serve first.");
  }

  function handleOverpass(): void {
    if (engine == null || engine.state.phase !== Phase.RECEPTION) {
      return;
    }
    if (candidate?.teamKey !== receivingTeam) {
      setInteractionHint("Tap the receiving player first.");
      return;
    }
    // Mirrors desktop on_overpass: the ball crossed straight back, logged as a poor reception.
    appendEvent({
      type: "reception",
      team: receivingTeam,
      player_id: candidate.playerId,
      rating: Rating.POOR,
      overpass: true,
    });
    setCandidate(null);
  }

  function handleCourtPlayerTap(teamKey: TeamKey, playerId: string): void {
    if (engine == null) {
      return;
    }
    if (armedBench?.teamKey === teamKey) {
      const event = exchangeEventFor(engine, teamKey, armedBench.playerId, playerId);
      setArmedBench(null);
      appendEvent(event);
      return;
    }
    chooseCandidate(teamKey, playerId);
  }

  function handleCourtTap(_x?: number, _y?: number): void {
    if (armedBench != null) {
      setArmedBench(null);
      setInteractionHint(null);
      return;
    }
    clearCourtTransientState();
  }

  function handleBenchPlayerTap(teamKey: TeamKey, playerId: string): void {
    if (engine == null) {
      return;
    }
    if (armedBench?.teamKey === teamKey && armedBench.playerId === playerId) {
      setArmedBench(null);
      setInteractionHint(null);
      return;
    }
    setArmedBench({ teamKey, playerId });
    setInteractionHint(null);
  }

  function updateNextSetLineup(teamKey: TeamKey, index: number, playerId: string): void {
    setNextSetDraft((current) => {
      if (current == null) {
        return current;
      }
      const lineup = [...current.lineups[teamKey]];
      lineup[index] = playerId;
      return {
        ...current,
        lineups: {
          ...current.lineups,
          [teamKey]: lineup,
        },
      };
    });
  }

  function rotateNextSet(teamKey: TeamKey, steps: number): void {
    setNextSetDraft((current) => (current == null ? current : rotateEditedSetLineup(current, teamKey, steps)));
  }

  function updateNextSetServingTeam(teamKey: TeamKey): void {
    setNextSetDraft((current) => (current == null ? current : { ...current, serving_team: teamKey }));
  }

  function updateNextSetLeftTeam(teamKey: TeamKey): void {
    setNextSetDraft((current) => (current == null ? current : { ...current, left_team: teamKey }));
  }

  function swapNextSetSides(): void {
    setNextSetDraft((current) => {
      const base = current ?? (nextSet == null ? null : cloneSetStartEvent(nextSet));
      return base == null ? base : { ...base, left_team: other(base.left_team) };
    });
  }

  function resetNextSetEditor(): void {
    if (nextSet == null) {
      return;
    }
    setNextSetDraft(cloneSetStartEvent(nextSet));
  }

  function startEditedNextSet(): void {
    if (engine == null || nextSetDraft == null) {
      return;
    }
    const error = validateEditedSetStart(nextSetDraft, engine.teams);
    if (error != null) {
      setInteractionHint(error);
      return;
    }
    appendEvent(nextSetDraft);
    setEditingNextSet(false);
  }

  function discardAutosave(): void {
    if (!clearAutosave()) {
      setStorageError("Autosave could not be cleared because browser storage is unavailable.");
      return;
    }
    setStorageError(null);
    setAutosave(null);
  }

  if (screen === "rosters") {
    return (
      <RosterLibraryScreen
        library={rosterLibrary}
        onSaveLibrary={persistRosterLibrary}
        onBack={() => setScreen(libraryReturnScreen)}
      />
    );
  }

  if (screen === "setup" && setupDraft != null) {
    return (
      <MatchSetupScreen
        library={rosterLibrary}
        draft={setupDraft}
        onDraftChange={setSetupDraft}
        onManageTeams={openRosterLibrary}
        onCancel={() => setScreen(session == null ? "startup" : "match")}
        onStart={startConfiguredMatch}
      />
    );
  }

  if (session == null) {
    return (
      <StartupScreen
        autosave={autosave}
        rosterCount={rosterLibrary.length}
        storageError={storageError}
        onResume={() => {
          if (autosave != null) {
            resetTransientInputs();
            setSession(autosave);
            setScreen("match");
          }
        }}
        onNewMatch={openSetup}
        onManageTeams={openRosterLibrary}
        onClearAutosave={discardAutosave}
      />
    );
  }

  if (engine == null) {
    return null;
  }

  const infoTone = statusTone(currentWarnings, currentAlerts);
  const lastEvent = session.events[session.events.length - 1] ?? null;
  const canRerateServe = engine.state.phase === Phase.RECEPTION && lastEvent?.type === "serve";
  const currentServeRating = lastEvent?.type === "serve" ? lastEvent.rating : null;
  const nextSetDraftError = nextSetDraft == null ? null : validateEditedSetStart(nextSetDraft, engine.teams);
  const prompt = courtPrompt(engine, candidate, pendingAttack, armedBench, interactionHint);
  const ratingContext = pendingAttack != null || engine.state.phase === Phase.ATTACK
    ? "attack"
    : engine.state.phase === Phase.RECEPTION
      ? "reception"
      : engine.state.phase === Phase.DEFENSE
        ? "dig"
        : "serve";
  const hints = CONTEXT_HINTS[ratingContext];
  const toastMessages = [...currentWarnings, ...currentAlerts];
  const leftTimeouts = engine.state.team[leftTeam].timeouts;
  const rightTimeouts = engine.state.team[rightTeam].timeouts;
  const leftDisplay = Math.min(leftTimeouts, 2);
  const rightDisplay = Math.min(rightTimeouts, 2);
  const leftDots = "●".repeat(leftDisplay) + "○".repeat(2 - leftDisplay);
  const rightDots = "●".repeat(rightDisplay) + "○".repeat(2 - rightDisplay);
  const leftName = teamLabel(engine.teams, leftTeam);
  const rightName = teamLabel(engine.teams, rightTeam);

  return (
    <main className="match-shell">
      <header className="match-topbar">
        <div className="match-score">
          <button
            type="button"
            className={`timeout-top-button ${leftTimeouts >= 2 ? "exhausted" : ""}`}
            onClick={() => appendEvent({ type: "timeout", team: leftTeam })}
            title={`Timeout ${leftName}`}
          >
            T {leftDots}
          </button>
          <span className="match-team">
            {engine.state.serving_team === leftTeam ? <span className="serve-dot">●</span> : null}
            <span>{leftName}</span>
            <small>{engine.state.set_scores[leftTeam]}</small>
          </span>
          <strong>{engine.state.scores[leftTeam]}</strong>
          <span className="match-score-sep">:</span>
          <strong>{engine.state.scores[rightTeam]}</strong>
          <span className="match-team">
            <small>{engine.state.set_scores[rightTeam]}</small>
            <span>{rightName}</span>
            {engine.state.serving_team === rightTeam ? <span className="serve-dot">●</span> : null}
          </span>
          <button
            type="button"
            className={`timeout-top-button ${rightTimeouts >= 2 ? "exhausted" : ""}`}
            onClick={() => appendEvent({ type: "timeout", team: rightTeam })}
            title={`Timeout ${rightName}`}
          >
            {rightDots} T
          </button>
        </div>
        <div className="match-meta">
          <span>Set {engine.state.set_number} · {phaseLabel(engine.state.phase)}</span>
          <span>
            Serving: {teamLabel(engine.teams, engine.state.serving_team)}
            {engine.expected_server() != null
              ? ` (${playerLabel(engine.teams[engine.state.serving_team], engine.expected_server()!)})`
              : ""}
            {engine.set_point_info() != null ? ` · ${engine.set_point_info()}` : ""}
          </span>
        </div>
        <div className="match-topbar-buttons">
          <button
            type="button"
            className={formationsEnabled ? "primary" : ""}
            onClick={() => setFormationsEnabled((current) => !current)}
          >
            Formations
          </button>
          <button
            type="button"
            className={showRolesEnabled ? "primary" : ""}
            onClick={() => setShowRolesEnabled((current) => !current)}
          >
            Show Roles
          </button>
          <button type="button" className={reportOpen ? "primary" : ""} onClick={() => setReportOpen((current) => !current)}>
            Report
          </button>
          <button
            type="button"
            className={trajectoryOpen ? "primary" : ""}
            onClick={() => setTrajectoryOpen((current) => !current)}
          >
            Charts
          </button>
          <button type="button" className={toolsOpen ? "primary" : ""} onClick={() => setToolsOpen((current) => !current)}>
            Tools
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => {
              if (window.confirm("Open match setup? Starting it will replace the current autosave.")) {
                openSetup();
              }
            }}
          >
            New
          </button>
        </div>
      </header>

      {storageError != null ? <div className="message-banner error">{storageError}</div> : null}

      <div className="match-body">
        <BenchPanel engine={engine} teamKey={leftTeam} armedBench={armedBench} onArm={handleBenchPlayerTap} />

        <div className="court-wrap">
          <CourtSurface
            leftTeamName={leftName}
            rightTeamName={rightName}
            tokens={courtTokens}
            trajectories={recentTrajectories}
            trajectoriesExpired={rallyTrajectoriesExpired}
            onPlayerTap={(teamKey, playerId) => handleCourtPlayerTap(teamKey as TeamKey, playerId)}
            onCourtTap={handleCourtTap}
            onTrajectory={handleCourtTrajectory}
          />
          {toastMessages.length > 0 ? (
            <div className={`court-toast ${infoTone}`}>
              {toastMessages.map((message) => (
                <p key={message}>{message}</p>
              ))}
            </div>
          ) : null}
        </div>

        <BenchPanel engine={engine} teamKey={rightTeam} armedBench={armedBench} onArm={handleBenchPlayerTap} />
      </div>

      <footer className="action-bar">
        <div className="action-prompt-row">
          <p className="action-prompt">{prompt}</p>
          {canRerateServe ? (
            <div className="serve-chip-strip">
              <span className="muted">serve:</span>
              {RATING_OPTIONS.map((rating) => (
                <button
                  key={rating}
                  type="button"
                  className={`serve-chip-mini rate-${RATING_CLASS[rating]} ${currentServeRating === rating ? "current" : ""}`}
                  onClick={() => rerateLastServe(rating)}
                >
                  {rating}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        {nextSet != null ? (
          <div className="action-row">
            <button
              type="button"
              className="action-big action-wide primary"
              onClick={() => appendEvent({ ...nextSet, left_team: nextSetDraft?.left_team ?? nextSet.left_team })}
            >
              Start set {nextSet.set_number}
            </button>
            <button type="button" className="action-big" onClick={swapNextSetSides}>
              ⇄<small>left: {teamLabel(engine.teams, nextSetDraft?.left_team ?? nextSet.left_team)}</small>
            </button>
            <button type="button" className="action-big" onClick={() => setEditingNextSet(true)}>
              Edit lineups
            </button>
            <button type="button" className="action-big rate-undo" onClick={undoLast} disabled={session.events.length <= 1}>
              ⟲<small>undo</small>
            </button>
          </div>
        ) : engine.state.phase === Phase.MATCH_OVER ? (
          <div className="action-row">
            <button type="button" className="action-big action-wide primary" onClick={() => setReportOpen(true)}>
              Match over — show report
            </button>
            <button type="button" className="action-big rate-undo" onClick={undoLast} disabled={session.events.length <= 1}>
              ⟲<small>undo</small>
            </button>
          </div>
        ) : (
          <div className="action-row">
            <button
              type="button"
              className="action-big point-btn"
              onClick={() => appendEvent({ type: "rally_point", team: leftTeam, reason: rallyReason || "manual" })}
            >
              ◀ point<small>{leftName}</small>
            </button>
            {RATING_OPTIONS.map((rating) => (
              <button
                key={rating}
                type="button"
                className={`action-big action-rate rate-${RATING_CLASS[rating]}`}
                onClick={() => handleRatingPick(rating)}
              >
                <span className="rate-symbol">{rating}</span>
                <small>{hints[rating]}</small>
              </button>
            ))}
            {ratingContext === "reception" ? (
              <button type="button" className="action-big rate-overpass" onClick={handleOverpass}>
                ↷<small>overpass</small>
              </button>
            ) : null}
            <button
              type="button"
              className="action-big point-btn"
              onClick={() => appendEvent({ type: "rally_point", team: rightTeam, reason: rallyReason || "manual" })}
            >
              point ▶<small>{rightName}</small>
            </button>
            <button type="button" className="action-big rate-undo" onClick={undoLast} disabled={session.events.length <= 1}>
              ⟲<small>undo</small>
            </button>
          </div>
        )}
      </footer>

      {editingNextSet && nextSetDraft != null ? (
        <div className="overlay-backdrop">
          <div className="overlay-panel">
            <NextSetEditor
              teams={engine.teams}
              draft={nextSetDraft}
              validationError={nextSetDraftError}
              onUpdateLineup={updateNextSetLineup}
              onRotate={rotateNextSet}
              onServingTeamChange={updateNextSetServingTeam}
              onLeftTeamChange={updateNextSetLeftTeam}
              onStart={startEditedNextSet}
              onReset={resetNextSetEditor}
              onClose={() => setEditingNextSet(false)}
            />
          </div>
        </div>
      ) : null}

      {reportOpen ? (
        <div className="overlay-backdrop">
          <div className="overlay-panel">
            <ReportPanel teams={engine.teams} events={session.events} onClose={() => setReportOpen(false)} />
          </div>
        </div>
      ) : null}

      {trajectoryOpen ? (
        <div className="overlay-backdrop">
          <div className="overlay-panel">
            <TrajectoryPanel
              config={session.config}
              teams={engine.teams}
              events={session.events}
              onClose={() => setTrajectoryOpen(false)}
            />
          </div>
        </div>
      ) : null}

      {toolsOpen ? (
        <div className="overlay-backdrop">
          <div className="overlay-panel">
            <div className="overlay-panel-header">
              <div>
                <h2>Match tools</h2>
                <p className="muted">
                  Autosaved {formatSavedAt(session.savedAt)} · Selected: {selectedPlayerText(engine, candidate)}
                </p>
              </div>
              <button type="button" className="ghost" onClick={() => setToolsOpen(false)}>
                Close
              </button>
            </div>

            <section className="team-grid">
              {TEAM_KEYS.map((teamKey) => (
                <TeamPanel key={teamKey} engine={engine} teamKey={teamKey} />
              ))}
            </section>

            <section className="controls-grid">
        {engine.state.phase === Phase.AWAIT_SERVE ? (
          <article className="control-card">
            <h2>Serve setup</h2>
            <p>{teamLabel(engine.teams, servingTeam)}</p>
            <label>
              Server
              <select value={servePlayer} onChange={(event) => setServePlayer((event.currentTarget as HTMLSelectElement).value)}>
                {serveOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">Drag from the server into the opponent court to log the serve trajectory.</p>
          </article>
        ) : null}

        {engine.state.phase === Phase.RECEPTION ? (
          <article className="control-card">
            <h2>Reception</h2>
            <p>{teamLabel(engine.teams, receivingTeam)}</p>
            <label>
              Receiver
              <select
                value={candidate?.teamKey === receivingTeam ? candidate.playerId : receptionPlayer}
                onChange={(event) => chooseCandidate(receivingTeam, (event.currentTarget as HTMLSelectElement).value)}
              >
                {receptionOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <RatingRow onPick={handleRatingPick} />
          </article>
        ) : null}

        {engine.state.phase === Phase.ATTACK ? (
          <article className="control-card">
            <h2>{pendingAttack == null ? "Attack" : "Attack ready"}</h2>
            <p>{teamLabel(engine.teams, pendingAttack?.teamKey ?? attackingTeam)}</p>
            <label>
              {pendingAttack == null ? "Attacker" : "Trajectory player"}
              <select
                value={pendingAttack?.playerId ?? (candidate?.teamKey === attackingTeam ? candidate.playerId : attackPlayer)}
                onChange={(event) => {
                  const playerId = (event.currentTarget as HTMLSelectElement).value;
                  if (pendingAttack != null) {
                    setCandidate({ teamKey: pendingAttack.teamKey, playerId });
                    setPendingAttack({ ...pendingAttack, playerId });
                    setAttackPlayer(playerId);
                  } else {
                    chooseCandidate(attackingTeam, playerId);
                  }
                }}
              >
                {(pendingAttack != null ? pendingAttackOptions : attackOptions).map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">
              {pendingAttack == null
                ? "Drag the attack path on the court, or rate a tapped attacker directly."
                : "Use the rating row to finalize the drawn attack."}
            </p>
            <RatingRow onPick={handleRatingPick} />
          </article>
        ) : null}

        {engine.state.phase === Phase.DEFENSE ? (
          <article className="control-card">
            <h2>{pendingAttack == null ? "Dig" : "Counter-attack ready"}</h2>
            <p>{teamLabel(engine.teams, pendingAttack?.teamKey ?? diggingTeam)}</p>
            <label>
              {pendingAttack == null ? "Digger" : "Counter-attacker"}
              <select
                value={pendingAttack?.playerId ?? (candidate?.teamKey === diggingTeam ? candidate.playerId : digPlayer)}
                onChange={(event) => {
                  const playerId = (event.currentTarget as HTMLSelectElement).value;
                  if (pendingAttack != null) {
                    setCandidate({ teamKey: pendingAttack.teamKey, playerId });
                    setPendingAttack({ ...pendingAttack, playerId });
                  } else {
                    chooseCandidate(diggingTeam, playerId);
                  }
                }}
              >
                {(pendingAttack != null ? pendingAttackOptions : digOptions).map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">
              {pendingAttack == null
                ? "Rate the dig or drag the counter-attack straight from the court."
                : "Use the rating row to finalize the counter-attack."}
            </p>
            <RatingRow onPick={handleRatingPick} />
          </article>
        ) : null}

        <article className="control-card">
          <h2>Rally point</h2>
          <label>
            Reason
            <input value={rallyReason} onInput={(event) => setRallyReason((event.currentTarget as HTMLInputElement).value)} />
          </label>
          <div className="button-grid">
            {TEAM_KEYS.map((teamKey) => (
              <button
                key={teamKey}
                type="button"
                onClick={() => appendEvent({ type: "rally_point", team: teamKey, reason: rallyReason || "manual" })}
              >
                Point {teamLabel(engine.teams, teamKey)}
              </button>
            ))}
          </div>
        </article>

        <article className="control-card">
          <h2>Timeout</h2>
          <div className="button-grid">
            {TEAM_KEYS.map((teamKey) => (
              <button key={teamKey} type="button" onClick={() => appendEvent({ type: "timeout", team: teamKey })}>
                Timeout {teamLabel(engine.teams, teamKey)}
              </button>
            ))}
          </div>
        </article>

        <article className="control-card">
          <h2>Manual corrections</h2>
          <p>
            {teamLabel(engine.teams, HOME)} {engine.state.scores[HOME]} : {engine.state.scores[AWAY]} {teamLabel(engine.teams, AWAY)}
          </p>
          <p className="muted">
            Serve: {teamLabel(engine.teams, engine.state.serving_team)} · P1 {teamLabel(engine.teams, HOME)} {p1Text(engine, HOME)} · {teamLabel(engine.teams, AWAY)} {p1Text(engine, AWAY)}
          </p>
          <div className="button-grid">
            <button type="button" onClick={() => applyManualScore(HOME, 1)}>
              {teamLabel(engine.teams, HOME)} +1
            </button>
            <button type="button" onClick={() => applyManualScore(HOME, -1)}>
              {teamLabel(engine.teams, HOME)} -1
            </button>
            <button type="button" onClick={() => appendEvent({ type: "serve_override", team: HOME })}>
              Serve → {teamLabel(engine.teams, HOME)}
            </button>
            <button type="button" onClick={() => appendEvent({ type: "rotation_adjust", team: HOME, steps: -1 })}>
              {teamLabel(engine.teams, HOME)} ⟲ rotate
            </button>
            <button type="button" onClick={() => appendEvent({ type: "rotation_adjust", team: HOME, steps: 1 })}>
              {teamLabel(engine.teams, HOME)} rotate ⟳
            </button>
            <button type="button" onClick={() => applyManualScore(AWAY, 1)}>
              {teamLabel(engine.teams, AWAY)} +1
            </button>
            <button type="button" onClick={() => applyManualScore(AWAY, -1)}>
              {teamLabel(engine.teams, AWAY)} -1
            </button>
            <button type="button" onClick={() => appendEvent({ type: "serve_override", team: AWAY })}>
              Serve → {teamLabel(engine.teams, AWAY)}
            </button>
            <button type="button" onClick={() => appendEvent({ type: "rotation_adjust", team: AWAY, steps: -1 })}>
              {teamLabel(engine.teams, AWAY)} ⟲ rotate
            </button>
            <button type="button" onClick={() => appendEvent({ type: "rotation_adjust", team: AWAY, steps: 1 })}>
              {teamLabel(engine.teams, AWAY)} rotate ⟳
            </button>
          </div>
        </article>
            </section>
          </div>
        </div>
      ) : null}
    </main>
  );
}
