"""중계 로그 (원본 PlayByPlayLogger.ts 대응). 문장 생성은 `gridiron.engine.commentary`."""
from __future__ import annotations

SCORING_TYPES_TD = {"passComplete", "run", "kickoffReturn", "puntReturn", "interceptionReturn",
                    "fumbleRecovery", "onsideKickRecovery"}


class PlayByPlayLogger:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.events: list[dict] = []
        self.scoring_summary: list[dict] = []
        self.quarter = 1
        self.game = None  # GameSim이 연결

    def _stamp(self, event: dict) -> dict:
        g = self.game
        if g is not None:
            event.setdefault("clock", g.clock)
            event.setdefault("quarter", self.quarter)
        return event

    def logEvent(self, event: dict) -> None:
        if event["type"] in ("quarter", "overtime"):
            self.quarter += 1
        self._stamp(event)
        if self.active:
            self.events.append(event)
        if self._is_score(event):
            self.scoring_summary.append({**event, "quarter": self.quarter})

    @staticmethod
    def _is_score(event: dict) -> bool:
        t = event["type"]
        if t in SCORING_TYPES_TD and event.get("td"):
            return True
        if t in ("fieldGoal", "extraPoint") and event.get("made"):
            return True
        if event.get("safety"):
            return True
        return False

    def logClock(self, **kw) -> None:
        if self.active:
            self.events.append({"type": "clock", "quarter": self.quarter, **kw})

    def logStat(self, t: int, pid: str | None, stat: str, amount: float) -> None:
        # 실시간 박스스코어용. MVP에서는 경기 후 집계만 쓰므로 기록하지 않는다.
        return

    def removeLastScore(self) -> None:
        if self.active:
            self.events.append({"type": "removeLastScore"})
        self.scoring_summary.append({"type": "removeLastScore"})

    def final_scoring_summary(self) -> list[dict]:
        out = []
        for i, cur in enumerate(self.scoring_summary):
            nxt = self.scoring_summary[i + 1] if i + 1 < len(self.scoring_summary) else None
            if nxt is not None and nxt["type"] == "removeLastScore":
                continue
            if cur["type"] == "removeLastScore":
                continue
            out.append(cur)
        return out
