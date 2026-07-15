/** Domain models. Mirrors core/models.py (see TRANSLATION.md). */

export const HOME = "home" as const;
export const AWAY = "away" as const;
export type TeamKey = typeof HOME | typeof AWAY;
export const TEAM_KEYS: readonly TeamKey[] = [HOME, AWAY];

export function other(team_key: TeamKey): TeamKey {
  return team_key === HOME ? AWAY : HOME;
}

export const Rating = {
  ERROR: "!", // fault -> immediate point for the opponent
  POOR: "-", // negative touch, rally continues
  GOOD: "+", // positive touch, rally continues
  PERFECT: "#", // terminal success: ace / kill (point), or perfect pass
} as const;
export type Rating = (typeof Rating)[keyof typeof Rating];
export const RATINGS: readonly Rating[] = [
  Rating.ERROR, Rating.POOR, Rating.GOOD, Rating.PERFECT,
];

export const Skill = {
  SERVE: "serve",
  RECEPTION: "reception",
  ATTACK: "attack",
  DIG: "dig",
} as const;
export type Skill = (typeof Skill)[keyof typeof Skill];

export const Role = {
  SETTER: "setter",
  OUTSIDE: "outside",
  OPPOSITE: "opposite",
  MIDDLE: "middle",
  LIBERO: "libero",
  UNIVERSAL: "universal",
} as const;
export type Role = (typeof Role)[keyof typeof Role];

const ROLE_ABBREV: Record<Role, string> = {
  setter: "S",
  outside: "OH",
  opposite: "OP",
  middle: "MB",
  libero: "L",
  universal: "U",
};

export function role_abbrev(role: Role): string {
  return ROLE_ABBREV[role];
}

export interface Player {
  number: number;
  name: string;
  role: Role;
  id: string;
}

/** uuid4().hex equivalent (32 lowercase hex chars). */
export function new_player_id(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export function make_player(
  number: number, name: string, role: Role = Role.UNIVERSAL, id?: string,
): Player {
  return { number, name, role, id: id ?? new_player_id() };
}

export function player_to_dict(p: Player): Record<string, unknown> {
  return { id: p.id, number: p.number, name: p.name, role: p.role };
}

export function player_from_dict(d: any): Player {
  return {
    number: d.number, name: d.name,
    role: (d.role ?? "universal") as Role, id: d.id,
  };
}

export interface Team {
  name: string;
  players: Player[];
  color: string;
}

export function make_team(
  name: string, players: Player[] = [], color = "#2e7d32",
): Team {
  return { name, players, color };
}

export function team_player(team: Team, player_id: string): Player | null {
  for (const p of team.players) {
    if (p.id === player_id) return p;
  }
  return null;
}

export function team_by_number(team: Team, number: number): Player | null {
  for (const p of team.players) {
    if (p.number === number) return p;
  }
  return null;
}

export function team_to_dict(t: Team): Record<string, unknown> {
  return {
    name: t.name, color: t.color,
    players: t.players.map(player_to_dict),
  };
}

export function team_from_dict(d: any): Team {
  return {
    name: d.name, color: d.color ?? "#2e7d32",
    players: (d.players ?? []).map(player_from_dict),
  };
}

export interface MatchConfig {
  sets_to_win: number; // best of 5
  points_per_set: number;
  points_deciding_set: number;
  min_lead: number;
  subs_per_set: number;
  libero_may_serve: boolean; // FIVB default false; some federations allow it
  deciding_set_switch_at: number;
  // app enters forced / learned libero exchanges itself (see
  // MatchEngine.next_auto_libero_swap); off = every exchange is manual
  auto_libero: boolean;
}

export function default_config(): MatchConfig {
  return {
    sets_to_win: 3,
    points_per_set: 25,
    points_deciding_set: 15,
    min_lead: 2,
    subs_per_set: 6,
    libero_may_serve: false,
    deciding_set_switch_at: 8,
    auto_libero: true,
  };
}

export function config_to_dict(c: MatchConfig): Record<string, unknown> {
  return {
    sets_to_win: c.sets_to_win,
    points_per_set: c.points_per_set,
    points_deciding_set: c.points_deciding_set,
    min_lead: c.min_lead,
    subs_per_set: c.subs_per_set,
    libero_may_serve: c.libero_may_serve,
    deciding_set_switch_at: c.deciding_set_switch_at,
    auto_libero: c.auto_libero,
  };
}

export function config_from_dict(d: any): MatchConfig {
  const c = default_config();
  for (const k of Object.keys(c) as (keyof MatchConfig)[]) {
    if (d != null && k in d) (c as any)[k] = d[k];
  }
  return c;
}
