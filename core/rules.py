"""Official-rule checks: set/match win conditions, substitution legality,
libero legality. All functions are pure and take primitives, so they are
trivially unit-testable and reusable by the engine and the UI.

The app is a scouting tool, not a referee: legality checks return WARNING
strings instead of raising, and the engine applies the event anyway --
what happened on court is the ground truth.
"""
from __future__ import annotations

from .models import MatchConfig
from .rotation import is_back_row


def is_deciding_set(config: MatchConfig, set_number: int) -> bool:
    return set_number == 2 * config.sets_to_win - 1


def set_target(config: MatchConfig, set_number: int) -> int:
    return (config.points_deciding_set if is_deciding_set(config, set_number)
            else config.points_per_set)


def set_winner(config: MatchConfig, set_number: int,
               score_a: int, score_b: int) -> int | None:
    """Return 0 if side A won the set, 1 if side B, None if it continues.
    A set is won at the target with at least `min_lead` difference (no cap)."""
    target = set_target(config, set_number)
    if score_a >= target and score_a - score_b >= config.min_lead:
        return 0
    if score_b >= target and score_b - score_a >= config.min_lead:
        return 1
    return None


def match_winner(config: MatchConfig, sets_a: int, sets_b: int) -> int | None:
    if sets_a >= config.sets_to_win:
        return 0
    if sets_b >= config.sets_to_win:
        return 1
    return None


def validate_substitution(lineup: list[str], liberos: list[str],
                          subs_used: int, sub_pairs: list[tuple[str, str]],
                          player_out: str, player_in: str,
                          config: MatchConfig) -> list[str]:
    """Warnings for a proposed substitution (player_in replaces player_out).

    Rules: max `subs_per_set` per team per set; a player and their
    substitute form an exclusive pair -- the starter may re-enter once,
    only for the player who replaced them, and that closes the pair.
    """
    w: list[str] = []
    if subs_used >= config.subs_per_set:
        w.append(f"substitution limit ({config.subs_per_set}) already reached")
    if player_out not in lineup:
        w.append("player going out is not on court")
    if player_in in lineup:
        w.append("player coming in is already on court")
    if player_in in liberos:
        w.append("a libero cannot enter through a substitution")

    forward = sub_pairs.count((player_out, player_in))
    reverse = sub_pairs.count((player_in, player_out))
    if forward + reverse >= 2:
        w.append("this exchange pair has already used its re-entry")
    for out_id, in_id in sub_pairs:
        if player_in == in_id and out_id != player_out:
            w.append("substitute already entered for a different player this set")
            break
        if player_in == out_id and in_id != player_out:
            w.append("player may only re-enter for the substitute who replaced them")
            break
    return w


def validate_libero_entry(lineup: list[str], partner_id: str,
                          team_is_serving: bool,
                          config: MatchConfig) -> list[str]:
    """Warnings for the libero entering the court in place of partner_id."""
    w: list[str] = []
    if partner_id not in lineup:
        w.append("replaced player is not on court")
        return w
    slot = lineup.index(partner_id)
    if not is_back_row(slot):
        w.append("libero may only replace a back-row player")
    if slot == 0 and team_is_serving and not config.libero_may_serve:
        w.append("libero may not serve (position P1 while team is serving)")
    return w


def validate_libero_exit(recorded_partner: str, partner_id: str) -> list[str]:
    if recorded_partner != partner_id:
        return ["libero must be exchanged back with the player they replaced"]
    return []
