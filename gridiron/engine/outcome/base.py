"""결과 모델 인터페이스."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..skeleton.game import GameSim
    from ..skeleton.types import PlayerGameSim


@dataclass
class PassPlan:
    """드롭백 한 번의 결과 계획. 골격이 이 계획대로 이벤트·통계·페널티를 처리한다."""

    pbw: dict = field(default_factory=dict)   # 블로커 → {"type": "OL"|"Other", "won": bool}
    qb_fumble: bool = False
    qb_fumble_yds: int = 0
    sack: bool = False
    scramble: bool = False
    target: "PlayerGameSim | None" = None
    defender: "PlayerGameSim | None" = None
    yds: int = 0                               # 경계 적용 전 원시 야드
    complete: bool = False
    interception: bool = False
    extra: dict = field(default_factory=dict)  # 결과 모델별 부가 정보 (콜, 압박, 기여분 등)


@dataclass
class RunPlan:
    carrier: "PlayerGameSim"
    rbw: dict | None = None
    yds: int = 0
    extra: dict = field(default_factory=dict)


class OutcomeModel(Protocol):
    name: str

    def prob_pass(self, g: "GameSim") -> float: ...
    def pass_play(self, g: "GameSim") -> PassPlan: ...
    def run_play(self, g: "GameSim", positions: list[str], scramble: bool) -> RunPlan: ...
    def prob_fumble(self, g: "GameSim", p: "PlayerGameSim") -> float: ...
    def prob_made_field_goal(self, g: "GameSim", kicker: "PlayerGameSim") -> float: ...
    def kickoff_return_yds(self, g: "GameSim", returner: "PlayerGameSim") -> int: ...
    def punt_distance(self, g: "GameSim", punter: "PlayerGameSim") -> int: ...
    def punt_return_yds(self, g: "GameSim", returner: "PlayerGameSim") -> int: ...
