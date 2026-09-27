"""최장 기록(Lng) 추적 — 페널티로 플레이가 취소되면 이전 값으로 되돌린다 (원본 LngTracker.ts)."""
from __future__ import annotations

import math


class LngTracker:
    def __init__(self) -> None:
        self.values: dict[str, dict] = {"team": {}, "player": {}}

    def log(self, kind: str, id_, stat: str, value: float, remove: bool = False) -> float:
        per_id = self.values[kind].setdefault(id_, {})
        x = per_id.setdefault(stat, {"previous": -math.inf, "current": -math.inf})
        if not remove:
            if value >= x["current"]:
                x["previous"] = x["current"]
                x["current"] = value
        elif value == x["current"]:
            x["current"] = x["previous"]
            x["previous"] = -math.inf
        return 0 if x["current"] == -math.inf else x["current"]
