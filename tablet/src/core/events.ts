/** Immutable match events. Mirrors core/events.py (see TRANSLATION.md).
 *
 * The event log is the single source of truth: current match state is always
 * derived by replaying events (see engine.ts), which makes undo trivially
 * correct (drop last event, replay).
 *
 * Unlike the Python side (frozen dataclasses + registry), events here are a
 * discriminated union on `type` whose shape equals the serialized dict form,
 * so files written by either side load on the other.
 */
import { Rating, TeamKey } from "./models";

// (x1, y1, x2, y2) in court metres; net at x=0, sidelines y=0 and y=9.
export type Trajectory = [number, number, number, number];

interface EventBase {
  // Wall-clock unix timestamp stamped by the UI when the event is entered.
  // Purely informational (video sync): replay/state never depends on it.
  ts?: number | null;
}

export interface SetStartEvent extends EventBase {
  type: "set_start";
  set_number: number;
  lineups: Record<TeamKey, string[]>; // team_key -> [player_id P1..P6]
  liberos: Record<TeamKey, string[]>; // team_key -> [player_id, ...]
  serving_team: TeamKey;
  left_team: TeamKey;
}

export interface ServeEvent extends EventBase {
  type: "serve";
  team: TeamKey;
  player_id: string;
  rating: Rating; // '+' is the default serve score (applied in event_from_dict)
  trajectory?: Trajectory | null;
}

/** `overpass: true`: the received ball crossed straight back over the net;
 * the rally continues with the serving team in the attack phase. */
export interface ReceptionEvent extends EventBase {
  type: "reception";
  team: TeamKey;
  player_id: string;
  rating: Rating;
  overpass?: boolean;
}

export interface AttackEvent extends EventBase {
  type: "attack";
  team: TeamKey;
  player_id: string;
  rating: Rating;
  trajectory?: Trajectory | null;
}

export interface DigEvent extends EventBase {
  type: "dig";
  team: TeamKey;
  player_id: string;
  rating: Rating;
}

/** Manual rally termination: net fault, referee decision, penalty point,
 * or anything the scouter could not follow. Awards the point to `team`. */
export interface RallyPointEvent extends EventBase {
  type: "rally_point";
  team: TeamKey;
  reason?: string;
}

export interface SubstitutionEvent extends EventBase {
  type: "substitution";
  team: TeamKey;
  player_out: string;
  player_in: string;
}

/** Toggles the libero: if off court, enters for partner; if on court,
 * partner returns. Not a substitution (unlimited, not counted). */
export interface LiberoSwapEvent extends EventBase {
  type: "libero_swap";
  team: TeamKey;
  libero_id: string;
  partner_id: string;
}

/** Manual rotation correction: rotates `team`'s lineup `steps` positions
 * clockwise (negative = counter-clockwise). Does NOT touch score or serve
 * possession -- the coach simply starts / stands in another rotation. */
export interface RotationAdjustEvent extends EventBase {
  type: "rotation_adjust";
  team: TeamKey;
  steps?: number;
}

/** Score correction. Does NOT touch serve possession or rotation. */
export interface ManualScoreEvent extends EventBase {
  type: "manual_score";
  team: TeamKey;
  delta: number;
}

/** Manually hand serve possession to `team` without a point/rotation. */
export interface ServeOverrideEvent extends EventBase {
  type: "serve_override";
  team: TeamKey;
}

export interface TimeoutEvent extends EventBase {
  type: "timeout";
  team: TeamKey;
}

export type MatchEvent =
  | SetStartEvent
  | ServeEvent
  | ReceptionEvent
  | AttackEvent
  | DigEvent
  | RallyPointEvent
  | SubstitutionEvent
  | LiberoSwapEvent
  | RotationAdjustEvent
  | ManualScoreEvent
  | ServeOverrideEvent
  | TimeoutEvent;

export type EventType = MatchEvent["type"];

function copy_traj(t: Trajectory | null | undefined): number[] | null {
  return t == null ? null : [t[0], t[1], t[2], t[3]];
}

/** Serialize with every field present (defaults filled in), matching the
 * dicts core/events.py::event_to_dict produces. */
export function event_to_dict(e: MatchEvent): Record<string, unknown> {
  const d: Record<string, unknown> = { type: e.type, ts: e.ts ?? null };
  switch (e.type) {
    case "set_start":
      d.set_number = e.set_number;
      d.lineups = { home: [...e.lineups.home], away: [...e.lineups.away] };
      d.liberos = { home: [...e.liberos.home], away: [...e.liberos.away] };
      d.serving_team = e.serving_team;
      d.left_team = e.left_team;
      break;
    case "serve":
      d.team = e.team;
      d.player_id = e.player_id;
      d.rating = e.rating;
      d.trajectory = copy_traj(e.trajectory);
      break;
    case "reception":
      d.team = e.team;
      d.player_id = e.player_id;
      d.rating = e.rating;
      d.overpass = e.overpass ?? false;
      break;
    case "attack":
      d.team = e.team;
      d.player_id = e.player_id;
      d.rating = e.rating;
      d.trajectory = copy_traj(e.trajectory);
      break;
    case "dig":
      d.team = e.team;
      d.player_id = e.player_id;
      d.rating = e.rating;
      break;
    case "rally_point":
      d.team = e.team;
      d.reason = e.reason ?? "manual";
      break;
    case "substitution":
      d.team = e.team;
      d.player_out = e.player_out;
      d.player_in = e.player_in;
      break;
    case "libero_swap":
      d.team = e.team;
      d.libero_id = e.libero_id;
      d.partner_id = e.partner_id;
      break;
    case "rotation_adjust":
      d.team = e.team;
      d.steps = e.steps ?? 1;
      break;
    case "manual_score":
      d.team = e.team;
      d.delta = e.delta;
      break;
    case "serve_override":
    case "timeout":
      d.team = e.team;
      break;
  }
  return d;
}

/** Parse a serialized event; missing optional fields get their Python
 * dataclass defaults; unknown keys are ignored; unknown type throws. */
export function event_from_dict(d: any): MatchEvent {
  const ts: number | null = d.ts ?? null;
  switch (d.type as EventType) {
    case "set_start":
      return {
        type: "set_start", ts,
        set_number: d.set_number,
        lineups: { home: [...d.lineups.home], away: [...d.lineups.away] },
        liberos: { home: [...d.liberos.home], away: [...d.liberos.away] },
        serving_team: d.serving_team,
        left_team: d.left_team,
      };
    case "serve":
      return {
        type: "serve", ts, team: d.team, player_id: d.player_id,
        rating: d.rating ?? Rating.GOOD,
        trajectory: d.trajectory == null ? null :
          [d.trajectory[0], d.trajectory[1], d.trajectory[2], d.trajectory[3]],
      };
    case "reception":
      return {
        type: "reception", ts, team: d.team, player_id: d.player_id,
        rating: d.rating, overpass: d.overpass ?? false,
      };
    case "attack":
      return {
        type: "attack", ts, team: d.team, player_id: d.player_id,
        rating: d.rating,
        trajectory: d.trajectory == null ? null :
          [d.trajectory[0], d.trajectory[1], d.trajectory[2], d.trajectory[3]],
      };
    case "dig":
      return {
        type: "dig", ts, team: d.team, player_id: d.player_id,
        rating: d.rating,
      };
    case "rally_point":
      return {
        type: "rally_point", ts, team: d.team,
        reason: d.reason ?? "manual",
      };
    case "substitution":
      return {
        type: "substitution", ts, team: d.team,
        player_out: d.player_out, player_in: d.player_in,
      };
    case "libero_swap":
      return {
        type: "libero_swap", ts, team: d.team,
        libero_id: d.libero_id, partner_id: d.partner_id,
      };
    case "rotation_adjust":
      return {
        type: "rotation_adjust", ts, team: d.team, steps: d.steps ?? 1,
      };
    case "manual_score":
      return { type: "manual_score", ts, team: d.team, delta: d.delta };
    case "serve_override":
      return { type: "serve_override", ts, team: d.team };
    case "timeout":
      return { type: "timeout", ts, team: d.team };
    default:
      throw new Error(`unknown event type ${d.type}`);
  }
}
