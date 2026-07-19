/** MatchEngine: applies the event log and derives the full match state.
 * Mirrors core/engine.py (see TRANSLATION.md) — the Python engine is the
 * reference; the conformance suite pins this file to it.
 *
 * Event-sourced: `events` is append-only; state is rebuilt by replay.
 * Undo therefore is exactly `events.pop(); replay()` and is correct across
 * points, rotations, substitutions and set boundaries by construction.
 *
 * Rule summary implemented here:
 * - rally scoring; set to 25 (deciding set 15), 2-point lead, no cap
 * - serving team wins rally -> same server, no rotation
 * - receiving team wins rally -> side-out: gains serve AND rotates clockwise
 *   (P2 becomes the new server at P1)
 * - sides switch after every set; in the deciding set also when the leading
 *   team reaches 8 points
 * - libero: back row only, may not serve (configurable), exchanges are not
 *   substitutions; engine flags mandatory swap-backs via pending_alerts()
 *   and, with config.auto_libero, proposes the exchanges itself one at a
 *   time via next_auto_libero_swap() (forced front-row exits, then learned
 *   re-entries at serve-receive) for the UIs to append on the scouter's
 *   behalf
 * - substitutions: 6 per set, exclusive pairs (validated as warnings)
 * - manual corrections are ordinary events: score +/-, serve possession,
 *   rotation adjust (lineup rotation only -- never score or serve)
 * - reception overpass: ball crosses straight back, serving team attacks
 * - blocked attacks (AttackEvent.block_touch): a deflection landing back in
 *   the attacker's own court keeps the rally alive with the ATTACKING team
 *   playing the next (cover) dig; any other landing behaves like a normal
 *   attack -- terminal ratings '#'/'!' award points exactly as always
 */
import * as rules from "./rules";
import { COVERED, classify_block_deflection } from "./blocks";
import {
  AttackEvent, DigEvent, LiberoSwapEvent, ManualScoreEvent, MatchEvent,
  RallyPointEvent, ReceptionEvent, RotationAdjustEvent, ServeEvent,
  ServeOverrideEvent, SetStartEvent, SubstitutionEvent, TimeoutEvent,
} from "./events";
import {
  AWAY, HOME, MatchConfig, Rating, Role, TEAM_KEYS, Team, TeamKey, other,
  team_player,
} from "./models";
import { BACK_ROW, LEFT, RIGHT, is_front_row, rotate_clockwise } from "./rotation";

export const Phase = {
  BEFORE_SET: "before_set", // waiting for a SetStartEvent
  AWAIT_SERVE: "await_serve", // between rallies
  RECEPTION: "reception",
  ATTACK: "attack",
  DEFENSE: "defense",
  SET_OVER: "set_over", // waiting for confirmation / next SetStart
  MATCH_OVER: "match_over",
} as const;
export type Phase = (typeof Phase)[keyof typeof Phase];

export interface TeamSetState {
  lineup: string[]; // P1..P6 player ids
  starting_lineup: string[];
  liberos: string[];
  subs_used: number;
  sub_pairs: [string, string][];
  libero_replaced: Record<string, string>; // libero -> partner off court
  // libero -> every partner they have entered for this set, in entry
  // order; drives the learned re-entry in next_auto_libero_swap()
  libero_partners: Record<string, string[]>;
  timeouts: number;
}

export function empty_team_set_state(): TeamSetState {
  return {
    lineup: [], starting_lineup: [], liberos: [],
    subs_used: 0, sub_pairs: [], libero_replaced: {},
    libero_partners: {}, timeouts: 0,
  };
}

export interface MatchState {
  phase: Phase;
  set_number: number;
  scores: Record<TeamKey, number>;
  set_scores: Record<TeamKey, number>;
  serving_team: TeamKey;
  set_first_server: TeamKey;
  left_team: TeamKey;
  switched_mid_set: boolean;
  attacking_team: TeamKey | null;
  last_set_winner: TeamKey | null;
  team: Record<TeamKey, TeamSetState>;
}

export function initial_match_state(): MatchState {
  return {
    phase: Phase.BEFORE_SET,
    set_number: 0,
    scores: { home: 0, away: 0 },
    set_scores: { home: 0, away: 0 },
    serving_team: HOME,
    set_first_server: HOME,
    left_team: HOME,
    switched_mid_set: false,
    attacking_team: null,
    last_set_winner: null,
    team: { home: empty_team_set_state(), away: empty_team_set_state() },
  };
}

export class MatchEngine {
  config: MatchConfig;
  teams: Record<TeamKey, Team>;
  events: MatchEvent[];
  state: MatchState;

  constructor(config: MatchConfig, teams: Record<TeamKey, Team>) {
    this.config = config;
    this.teams = teams;
    this.events = [];
    this.state = initial_match_state();
  }

  // ------------------------------------------------------------------ api

  /** Validate + apply one event. Returns warnings (event is applied
   * regardless -- the court is the ground truth, we only warn). */
  append(event: MatchEvent): string[] {
    const warnings = this._apply(event);
    this.events.push(event);
    return warnings;
  }

  undo(): MatchEvent | null {
    if (!this.events.length) return null;
    const removed = this.events.pop()!;
    this._replay();
    return removed;
  }

  load_events(events: MatchEvent[]): void {
    this.events = [...events];
    this._replay();
  }

  _replay(): void {
    const saved = this.events;
    this.state = initial_match_state();
    this.events = [];
    for (const e of saved) {
      this._apply(e);
      this.events.push(e);
    }
  }

  // -------------------------------------------------------------- helpers

  side_of(team_key: TeamKey): string {
    return this.state.left_team === team_key ? LEFT : RIGHT;
  }

  team_on_side(side: string): TeamKey {
    return side === LEFT ? this.state.left_team : other(this.state.left_team);
  }

  receiving_team(): TeamKey {
    return other(this.state.serving_team);
  }

  expected_server(): string | null {
    const lineup = this.state.team[this.state.serving_team].lineup;
    return lineup.length ? lineup[0] : null;
  }

  rally_live(): boolean {
    const p = this.state.phase;
    return p === Phase.RECEPTION || p === Phase.ATTACK || p === Phase.DEFENSE;
  }

  /** 'set point HOME' / 'match point AWAY' style info, else null. */
  set_point_info(): string | null {
    const st = this.state;
    if (st.phase === Phase.BEFORE_SET || st.set_number === 0) return null;
    const target = rules.set_target(this.config, st.set_number);
    for (const tk of TEAM_KEYS) {
      const score = st.scores[tk];
      const opp = st.scores[other(tk)];
      if (score + 1 >= target && score + 1 - opp >= this.config.min_lead) {
        const sets_after = st.set_scores[tk] + 1;
        const kind = sets_after >= this.config.sets_to_win
          ? "match point" : "set point";
        return `${kind} ${this.teams[tk].name}`;
      }
    }
    return null;
  }

  /** Mandatory actions the scouter must be reminded of between rallies:
   * libero swap-backs when the replaced slot rotates to the front row or
   * is about to serve. */
  pending_alerts(): string[] {
    const alerts: string[] = [];
    if (this.state.phase !== Phase.AWAIT_SERVE) return alerts;
    for (const tk of TEAM_KEYS) {
      const ts = this.state.team[tk];
      for (const [libero_id, partner_id] of Object.entries(ts.libero_replaced)) {
        if (!ts.lineup.includes(libero_id)) continue;
        const slot = ts.lineup.indexOf(libero_id);
        const lib = team_player(this.teams[tk], libero_id);
        const partner = team_player(this.teams[tk], partner_id);
        const lib_n = lib ? `#${lib.number}` : "?";
        const par_n = partner ? `#${partner.number}` : "?";
        if (is_front_row(slot)) {
          alerts.push(
            `${this.teams[tk].name}: libero ${lib_n} rotated to the `
            + `front row - ${par_n} must return`);
        } else if (slot === 0 && tk === this.state.serving_team
            && !this.config.libero_may_serve) {
          alerts.push(
            `${this.teams[tk].name}: libero ${lib_n} is at P1 and `
            + `may not serve - ${par_n} must return`);
        }
      }
    }
    return alerts;
  }

  /** The next libero exchange the app should enter on the scouter's
   * behalf, or null. The UIs call this in a loop after appending a
   * user event (each returned event must be appended before asking
   * again):
   * 1. forced exits -- a libero rotated to the front row, or stands
   *    at P1 while their team serves and may not: the recorded
   *    partner returns;
   * 2. learned re-entry -- at serve-receive the receiving team's
   *    libero re-enters for a previous partner now in the back row,
   *    falling back to a back-row middle. The libero's first entry
   *    of a set is always manual: that is how the coach's actual
   *    pairing is expressed. */
  next_auto_libero_swap(): LiberoSwapEvent | null {
    if (!this.config.auto_libero) return null;
    const st = this.state;
    if (st.phase !== Phase.AWAIT_SERVE) return null;
    for (const tk of TEAM_KEYS) { // 1) forced exits
      const ts = st.team[tk];
      for (const [lib_id, partner_id] of Object.entries(ts.libero_replaced)) {
        if (!ts.lineup.includes(lib_id)) continue;
        const slot = ts.lineup.indexOf(lib_id);
        if (is_front_row(slot) || (
            slot === 0 && tk === st.serving_team
            && !this.config.libero_may_serve)) {
          return {
            type: "libero_swap", ts: null, team: tk,
            libero_id: lib_id, partner_id, auto: true,
          };
        }
      }
    }
    const tk = this.receiving_team(); // 2) re-entry
    const ts = st.team[tk];
    if (ts.liberos.some((lib) => ts.lineup.includes(lib))) {
      return null; // one libero on court at a time
    }
    const back = BACK_ROW.map((i) => ts.lineup[i]); // P1, P6, P5 -- P1 first:
    for (const lib_id of ts.liberos) { // they just rotated back
      const learned = ts.libero_partners[lib_id] ?? [];
      if (!learned.length) continue; // first entry of the set: manual
      let partner = back.find((p) => learned.includes(p)) ?? null;
      if (partner == null) {
        const team = this.teams[tk];
        partner = back.find((p) => {
          const pl = team_player(team, p);
          return pl != null && pl.role === Role.MIDDLE;
        }) ?? null;
      }
      if (partner != null) {
        return {
          type: "libero_swap", ts: null, team: tk,
          libero_id: lib_id, partner_id: partner, auto: true,
        };
      }
    }
    return null;
  }

  /** Prefill for the next set: sides switch, first serve alternates,
   * lineups default to the previous starting lineups (with the libero
   * exchange undone). */
  suggest_next_set_start(): SetStartEvent | null {
    const st = this.state;
    if (st.phase !== Phase.SET_OVER && st.phase !== Phase.BEFORE_SET) {
      return null;
    }
    if (st.phase === Phase.BEFORE_SET) return null;
    return {
      type: "set_start",
      ts: null,
      set_number: st.set_number + 1,
      lineups: {
        home: [...st.team.home.starting_lineup],
        away: [...st.team.away.starting_lineup],
      },
      liberos: {
        home: [...st.team.home.liberos],
        away: [...st.team.away.liberos],
      },
      serving_team: other(st.set_first_server),
      left_team: other(st.left_team),
    };
  }

  // ---------------------------------------------------------------- apply

  _apply(e: MatchEvent): string[] {
    switch (e.type) {
      case "set_start": return this._on_set_start(e);
      case "serve": return this._on_serve(e);
      case "reception": return this._on_reception(e);
      case "attack": return this._on_attack(e);
      case "dig": return this._on_dig(e);
      case "rally_point": return this._on_rally_point(e);
      case "substitution": return this._on_substitution(e);
      case "libero_swap": return this._on_libero_swap(e);
      case "manual_score": return this._on_manual_score(e);
      case "rotation_adjust": return this._on_rotation_adjust(e);
      case "serve_override": return this._on_serve_override(e);
      case "timeout": return this._on_timeout(e);
      default:
        return [`unknown event type ${(e as any).type}`];
    }
  }

  _on_set_start(e: SetStartEvent): string[] {
    const w: string[] = [];
    const st = this.state;
    if (st.phase !== Phase.BEFORE_SET && st.phase !== Phase.SET_OVER) {
      w.push("set started while previous set was not finished");
    }
    if (e.set_number !== st.set_number + 1) {
      w.push(`unexpected set number ${e.set_number} `
        + `(expected ${st.set_number + 1})`);
    }
    st.set_number = e.set_number;
    st.scores = { home: 0, away: 0 };
    st.serving_team = e.serving_team;
    st.set_first_server = e.serving_team;
    st.left_team = e.left_team;
    st.switched_mid_set = false;
    st.attacking_team = null;
    st.phase = Phase.AWAIT_SERVE;
    for (const tk of TEAM_KEYS) {
      const lineup = [...e.lineups[tk]];
      if (lineup.length !== 6 || new Set(lineup).size !== 6) {
        w.push(`${this.teams[tk].name}: lineup must be 6 distinct players`);
      }
      const libs = [...(e.liberos[tk] ?? [])];
      const bad = libs.filter((p) => lineup.includes(p));
      if (bad.length) {
        w.push(`${this.teams[tk].name}: libero cannot be in the `
          + `starting lineup`);
      }
      st.team[tk] = {
        ...empty_team_set_state(),
        lineup, starting_lineup: [...lineup], liberos: libs,
      };
    }
    return w;
  }

  _on_serve(e: ServeEvent): string[] {
    const w: string[] = [];
    const st = this.state;
    if (st.phase !== Phase.AWAIT_SERVE) {
      w.push(`serve entered during phase '${st.phase}'`);
    }
    if (e.team !== st.serving_team) {
      w.push(`${this.teams[e.team].name} served but `
        + `${this.teams[st.serving_team].name} has serve possession`);
    }
    const expected = this.expected_server();
    if (expected && e.player_id !== expected) {
      const p = team_player(this.teams[e.team], expected);
      w.push(`expected server is #${p ? p.number : "?"} (P1)`);
    }
    if (e.rating === Rating.PERFECT) { // ace
      this._award_point(e.team);
    } else if (e.rating === Rating.ERROR) { // service fault
      this._award_point(other(e.team));
    } else {
      st.phase = Phase.RECEPTION;
      st.attacking_team = null;
    }
    return w;
  }

  _on_reception(e: ReceptionEvent): string[] {
    const w: string[] = [];
    const st = this.state;
    if (st.phase !== Phase.RECEPTION) {
      w.push(`reception entered during phase '${st.phase}'`);
    }
    if (e.team === st.serving_team) {
      w.push("reception charged to the serving team");
    }
    if (e.rating === Rating.ERROR) { // aced
      this._award_point(other(e.team));
    } else if (e.overpass) { // ball straight back
      st.phase = Phase.ATTACK;
      st.attacking_team = other(e.team);
    } else {
      st.phase = Phase.ATTACK;
      st.attacking_team = e.team;
    }
    return w;
  }

  _on_attack(e: AttackEvent): string[] {
    const w: string[] = [];
    const st = this.state;
    if (st.phase === Phase.DEFENSE) {
      // scouter skipped touches -- either the unrated dig (other team
      // attacks) or the whole opposing counter-attack (same team
      // attacks again). Both are legitimate fast-rally shorthand.
      st.attacking_team = e.team;
      st.phase = Phase.ATTACK;
    }
    if (st.phase !== Phase.ATTACK) {
      w.push(`attack entered during phase '${st.phase}'`);
    } else if (st.attacking_team && e.team !== st.attacking_team) {
      // scouter missed the holding team's attack: possession simply
      // follows the drawn attack, no warning
      st.attacking_team = e.team;
    }
    if (e.rating === Rating.PERFECT) { // kill
      this._award_point(e.team);
    } else if (e.rating === Rating.ERROR) { // out / net / blocked down
      this._award_point(other(e.team));
    } else {
      st.phase = Phase.DEFENSE;
      const returned = (e.block_touch != null && e.trajectory != null
        && classify_block_deflection(
          this.side_of(e.team),
          e.trajectory[2], e.trajectory[3]) === COVERED);
      // a block deflection back into the attacker's court means the
      // attacking team itself must cover (dig) the next ball
      st.attacking_team = returned ? other(e.team) : e.team;
    }
    return w;
  }

  _on_dig(e: DigEvent): string[] {
    const w: string[] = [];
    const st = this.state;
    if (st.phase !== Phase.DEFENSE) {
      w.push(`dig entered during phase '${st.phase}'`);
    }
    if (st.attacking_team && e.team !== other(st.attacking_team)) {
      w.push("dig charged to the attacking team");
    }
    if (e.rating === Rating.ERROR) { // ball hit the floor / shanked
      this._award_point(other(e.team));
    } else {
      st.phase = Phase.ATTACK;
      st.attacking_team = e.team; // counter-attack
    }
    return w;
  }

  _on_rally_point(e: RallyPointEvent): string[] {
    const w: string[] = [];
    const p = this.state.phase;
    if (p === Phase.BEFORE_SET || p === Phase.SET_OVER
        || p === Phase.MATCH_OVER) {
      w.push(`point awarded during phase '${p}'`);
    }
    this._award_point(e.team);
    return w;
  }

  _on_substitution(e: SubstitutionEvent): string[] {
    const st = this.state;
    const ts = st.team[e.team];
    const w: string[] = [];
    if (this.rally_live()) {
      w.push("substitution during a live rally");
    }
    w.push(...rules.validate_substitution(
      ts.lineup, ts.liberos, ts.subs_used, ts.sub_pairs,
      e.player_out, e.player_in, this.config));
    if (ts.lineup.includes(e.player_out)) {
      ts.lineup[ts.lineup.indexOf(e.player_out)] = e.player_in;
    }
    ts.subs_used += 1;
    ts.sub_pairs.push([e.player_out, e.player_in]);
    return w;
  }

  _on_libero_swap(e: LiberoSwapEvent): string[] {
    const st = this.state;
    const ts = st.team[e.team];
    const w: string[] = [];
    if (this.rally_live()) {
      w.push("libero exchange during a live rally");
    }
    if (!ts.liberos.includes(e.libero_id)) {
      // a libero the scouter never designated: adopt them rather than
      // let the UIs record a substitution and silently spend one of the
      // 6 -- the tap itself is the designation
      const p = team_player(this.teams[e.team], e.libero_id);
      if (p != null && p.role === Role.LIBERO) {
        ts.liberos.push(e.libero_id);
        w.push(`#${p.number} was not registered as libero `
          + `for this set -- registered now`);
      } else {
        w.push("player is not registered as libero");
      }
    }
    if (ts.lineup.includes(e.libero_id)) { // libero exits
      const recorded = ts.libero_replaced[e.libero_id] ?? e.partner_id;
      w.push(...rules.validate_libero_exit(recorded, e.partner_id));
      ts.lineup[ts.lineup.indexOf(e.libero_id)] = recorded;
      delete ts.libero_replaced[e.libero_id];
    } else { // libero enters
      w.push(...rules.validate_libero_entry(
        ts.lineup, e.partner_id,
        e.team === st.serving_team, this.config));
      if (ts.lineup.includes(e.partner_id)) {
        ts.lineup[ts.lineup.indexOf(e.partner_id)] = e.libero_id;
        ts.libero_replaced[e.libero_id] = e.partner_id;
        const partners = (ts.libero_partners[e.libero_id] ??= []);
        if (!partners.includes(e.partner_id)) {
          partners.push(e.partner_id);
        }
      }
    }
    return w;
  }

  _on_manual_score(e: ManualScoreEvent): string[] {
    const st = this.state;
    st.scores[e.team] = Math.max(0, st.scores[e.team] + e.delta);
    this._check_set_end();
    return [];
  }

  _on_rotation_adjust(e: RotationAdjustEvent): string[] {
    const w: string[] = [];
    if (this.rally_live()) {
      w.push("rotation adjusted during a live rally");
    }
    const ts = this.state.team[e.team];
    const steps = e.steps ?? 1;
    const n = ((steps % 6) + 6) % 6; // Python's `steps % 6` (always >= 0)
    for (let i = 0; i < n; i++) {
      ts.lineup = rotate_clockwise(ts.lineup);
    }
    return w;
  }

  _on_serve_override(e: ServeOverrideEvent): string[] {
    this.state.serving_team = e.team;
    return [];
  }

  _on_timeout(e: TimeoutEvent): string[] {
    const ts = this.state.team[e.team];
    ts.timeouts += 1;
    return ts.timeouts > 2 ? ["timeout limit (2 per set) exceeded"] : [];
  }

  // --------------------------------------------------------------- points

  _award_point(winner: TeamKey): void {
    const st = this.state;
    st.scores[winner] += 1;
    if (winner !== st.serving_team) {
      // side-out: winner gains serve and rotates clockwise
      const ts = st.team[winner];
      ts.lineup = rotate_clockwise(ts.lineup);
      st.serving_team = winner;
    }
    st.attacking_team = null;
    // deciding-set mid-set side switch when the leading team reaches 8
    if (rules.is_deciding_set(this.config, st.set_number)
        && !st.switched_mid_set
        && st.scores[winner] === this.config.deciding_set_switch_at) {
      st.left_team = other(st.left_team);
      st.switched_mid_set = true;
    }
    this._check_set_end();
  }

  _check_set_end(): void {
    const st = this.state;
    const idx = rules.set_winner(this.config, st.set_number,
      st.scores[HOME], st.scores[AWAY]);
    if (st.phase === Phase.SET_OVER || st.phase === Phase.MATCH_OVER) {
      // set already awarded -- never award twice; but a manual score
      // correction may re-open the set
      if (idx === null && st.last_set_winner !== null) {
        st.set_scores[st.last_set_winner] -= 1;
        st.last_set_winner = null;
        st.phase = Phase.AWAIT_SERVE;
      }
      return;
    }
    if (idx === null) {
      if (st.phase !== Phase.BEFORE_SET) {
        st.phase = Phase.AWAIT_SERVE;
      }
      return;
    }
    const winner = idx === 0 ? HOME : AWAY;
    st.set_scores[winner] += 1;
    st.last_set_winner = winner;
    if (rules.match_winner(this.config, st.set_scores[HOME],
        st.set_scores[AWAY]) !== null) {
      st.phase = Phase.MATCH_OVER;
    } else {
      st.phase = Phase.SET_OVER;
    }
  }
}
