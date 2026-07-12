"""Domain models. Pure Python, no Qt imports."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

HOME = "home"
AWAY = "away"
TEAM_KEYS = (HOME, AWAY)


def other(team_key: str) -> str:
    return AWAY if team_key == HOME else HOME


class Rating(str, Enum):
    ERROR = "!"    # fault -> immediate point for the opponent
    POOR = "-"     # negative touch, rally continues
    GOOD = "+"     # positive touch, rally continues
    PERFECT = "#"  # terminal success: ace / kill (point), or perfect pass

    @property
    def symbol(self) -> str:
        return self.value


class Skill(str, Enum):
    SERVE = "serve"
    RECEPTION = "reception"
    ATTACK = "attack"
    DIG = "dig"


class Role(str, Enum):
    SETTER = "setter"
    OUTSIDE = "outside"
    OPPOSITE = "opposite"
    MIDDLE = "middle"
    LIBERO = "libero"
    UNIVERSAL = "universal"

    @property
    def abbrev(self) -> str:
        return {
            Role.SETTER: "S",
            Role.OUTSIDE: "OH",
            Role.OPPOSITE: "OP",
            Role.MIDDLE: "MB",
            Role.LIBERO: "L",
            Role.UNIVERSAL: "U",
        }[self]


@dataclass
class Player:
    number: int
    name: str
    role: Role = Role.UNIVERSAL
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {"id": self.id, "number": self.number, "name": self.name,
                "role": self.role.value}

    @classmethod
    def from_dict(cls, d: dict) -> "Player":
        return cls(number=d["number"], name=d["name"],
                   role=Role(d.get("role", "universal")), id=d["id"])


@dataclass
class Team:
    name: str
    players: list[Player] = field(default_factory=list)
    color: str = "#2e7d32"

    def player(self, player_id: str) -> Player | None:
        for p in self.players:
            if p.id == player_id:
                return p
        return None

    def by_number(self, number: int) -> Player | None:
        for p in self.players:
            if p.number == number:
                return p
        return None

    def to_dict(self) -> dict:
        return {"name": self.name, "color": self.color,
                "players": [p.to_dict() for p in self.players]}

    @classmethod
    def from_dict(cls, d: dict) -> "Team":
        return cls(name=d["name"], color=d.get("color", "#2e7d32"),
                   players=[Player.from_dict(p) for p in d.get("players", [])])


@dataclass
class MatchConfig:
    sets_to_win: int = 3            # best of 5
    points_per_set: int = 25
    points_deciding_set: int = 15
    min_lead: int = 2
    subs_per_set: int = 6
    libero_may_serve: bool = False  # FIVB default; some federations allow it
    deciding_set_switch_at: int = 8

    def to_dict(self) -> dict:
        return {
            "sets_to_win": self.sets_to_win,
            "points_per_set": self.points_per_set,
            "points_deciding_set": self.points_deciding_set,
            "min_lead": self.min_lead,
            "subs_per_set": self.subs_per_set,
            "libero_may_serve": self.libero_may_serve,
            "deciding_set_switch_at": self.deciding_set_switch_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MatchConfig":
        return cls(**{k: d[k] for k in cls().to_dict() if k in d})
