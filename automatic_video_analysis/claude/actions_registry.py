"""Registry of volleyball actions the detector can look for.

Each action carries the cue text that goes into the Gemini prompt. `reliable`
marks actions we've actually validated (serve). The rest are experimental — they
lack the referee-whistle audio anchor that makes serves easy, so expect lower
accuracy until tuned.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionType:
    key: str          # machine key, e.g. "serve"
    label: str        # UI label, e.g. "Serve"
    cues: str         # instruction text injected into the prompt
    reliable: bool    # True = validated; False = experimental


ACTION_TYPES: list[ActionType] = [
    ActionType(
        key="serve",
        label="Serve",
        reliable=True,
        cues=(
            "SERVE — starts each rally. A player standing behind their end line tosses "
            "the ball and strikes it over the net (jump, standing float, or underhand). "
            "Just before it the two teams are stationary in rotation; immediately after, "
            "live rally play begins. Report the moment of ball contact on the serve. "
            "Judge only from what is visible in the video."
        ),
    ),
    ActionType(
        key="spike",
        label="Spike / Attack",
        reliable=False,
        cues=(
            "SPIKE (attack) — a forceful, usually downward hit by a player near the net "
            "(or a back-row player jumping behind the 3m line) intended to end the rally, "
            "normally right after a set. Report the moment the attacker's hand contacts "
            "the ball. Do not report gentle tips/sets."
        ),
    ),
    ActionType(
        key="block",
        label="Block",
        reliable=False,
        cues=(
            "BLOCK — one or more defenders at the net jump with hands above the net to "
            "stop an attack. Report the moment of the block contact/attempt at the net."
        ),
    ),
    ActionType(
        key="reception",
        label="Reception (serve-receive)",
        reliable=False,
        cues=(
            "RECEPTION — the first contact of a team receiving a serve, usually a forearm "
            "pass (platform) by a back-row player. Report the moment of contact."
        ),
    ),
    ActionType(
        key="dig",
        label="Dig",
        reliable=False,
        cues=(
            "DIG — a defensive contact that keeps an attacked (spiked) ball alive, often a "
            "forearm pass or diving save. Report the moment of contact."
        ),
    ),
]

ACTIONS_BY_KEY: dict[str, ActionType] = {a.key: a for a in ACTION_TYPES}


def cues_for(keys: list[str]) -> list[ActionType]:
    return [ACTIONS_BY_KEY[k] for k in keys if k in ACTIONS_BY_KEY]
