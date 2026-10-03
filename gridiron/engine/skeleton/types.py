"""경기 중 선수·팀 표현 (원본 types.ts)."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


def new_stat() -> defaultdict:
    return defaultdict(float)


@dataclass(eq=False)
class PlayerGameSim:
    """경기 엔진 안의 선수. `composite`는 0–1 척도의 합성 능력(원본 compositeRating)."""

    id: str
    name: str
    pos: str                      # 엔진 포지션 (QB, RB, …)
    age: float
    composite: dict[str, float]
    ovrs: dict[str, float]        # 엔진 포지션별 종합 (0–100)
    attributes: dict[str, float] = field(default_factory=dict)  # 원래 1–20 능력치 (결과 모델용)
    stat: defaultdict = field(default_factory=new_stat)
    season_stats: dict[str, float] = field(default_factory=dict)
    injured: bool = False
    cond: float = 1.0             # 주간 컨디션 배율 (M4)
    new_injury: bool = False
    playing_through_injury: bool = False

    def __hash__(self) -> int:  # dict/set 키로 쓰기 위해 id 기준
        return hash(self.id)

    def __repr__(self) -> str:
        return f"<{self.pos} {self.name}>"


@dataclass
class TeamGameSim:
    id: int                        # 0 = 홈, 1 = 원정
    abbr: str
    players: list[PlayerGameSim]
    depth: dict[str, list[PlayerGameSim]]
    stat: defaultdict = field(default_factory=new_stat)
    composite: dict[str, float] = field(default_factory=dict)
    pace: float = 1.0
    front: str = "4-3"
    # ── M4: 전술·준비 (없으면 리그 평균 전술) ──
    tactics: object = None             # gridiron.tactics.model.Tactics
    familiarity: dict | None = None
    prep: dict | None = None           # 이번 주 훈련 준비값
    scout: dict | None = None          # 상대에 대한 사전 정보 (scouting.prior)
    ai_controlled: bool = True         # False면 사용자 전술의 λ를 그대로 쓴다

    def __post_init__(self) -> None:
        self.stat["ptsQtrs"] = [0]
        self.stat["pts"] = 0
