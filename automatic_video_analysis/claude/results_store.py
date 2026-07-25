"""Persistent, accumulating store of detected actions across runs.

Each record is one detected action (a dict) with detection fields plus, for serves
that were analysed, court-placement fields. Backed by a JSON file so results
survive between sessions and can be sliced by team / player / action.

Kept deliberately simple (a JSON list). If it ever needs real querying at scale,
swap the backend for SQLite behind the same interface.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Optional


# fields we filter/columnate on
FILTER_FIELDS = ("team", "player", "action")


def normalize_team(value) -> str:
    """Light hygiene so 'FRA' / 'fra' / ' FRA ' don't fragment filters/colors."""
    return str(value or "").strip().upper()


class ResultsStore:
    def __init__(self, path: str):
        self.path = path
        self.records: list[dict] = []
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.records = data if isinstance(data, list) else data.get("records", [])
            except Exception:
                self.records = []

    def save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self.records, fh, indent=2, ensure_ascii=False)

    def add_run(self, rows: list[dict], source: str = "", model: str = "") -> int:
        """Append a run's result rows, tagging each with source/model/run time."""
        run = _dt.datetime.now().isoformat(timespec="seconds")
        added = 0
        for r in rows:
            rec = dict(r)
            if "team" in rec:
                rec["team"] = normalize_team(rec["team"])
            rec.setdefault("source", source)
            rec.setdefault("model", model)
            rec.setdefault("run", run)
            self.records.append(rec)
            added += 1
        self.save()
        return added

    def clear(self):
        self.records = []
        self.save()

    def distinct(self, field: str) -> list[str]:
        return sorted({str(r.get(field)) for r in self.records
                       if r.get(field) not in (None, "", "unknown")})

    def filter(self, team: Optional[str] = None, player: Optional[str] = None,
               action: Optional[str] = None) -> list[dict]:
        def ok(r: dict) -> bool:
            if team and str(r.get("team")) != team:
                return False
            if player and str(r.get("player")) != player:
                return False
            if action and str(r.get("action")) != action:
                return False
            return True
        return [r for r in self.records if ok(r)]

    @staticmethod
    def serve_placements(records: list[dict]) -> list[dict]:
        """Serve records that carry court placement, shaped for court_chart."""
        out = []
        for r in records:
            if r.get("action") != "serve" or "serve_from_lateral" not in r:
                continue
            out.append({
                "team": r.get("team", "?"),
                "player": r.get("player", "?"),
                "serve_from_lateral": r.get("serve_from_lateral", 0.5),
                "target_depth": r.get("target_depth", 0.5),
                "target_lateral": r.get("target_lateral", 0.5),
                "target_zone": r.get("target_zone", 0),
            })
        return out
