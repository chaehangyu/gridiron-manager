"""경기 규칙·보정 계수 (원본 g.get 설정 대응). 값은 config/league_rules.yaml에서 덮어쓸 수 있다."""
from __future__ import annotations

from dataclasses import dataclass, fields

from ...config import load


@dataclass
class GameSettings:
    quarter_length: float = 15.0          # 분
    num_periods: int = 4
    overtime_length: float = 10.0         # 정규시즌 연장 (분)
    overtime_length_playoffs: float = 15.0
    overtime_type: str = "bothPossess"    # suddenDeath | exceptFg | bothPossess
    overtime_type_playoffs: str = "bothPossess"
    max_overtimes: int = 1                # 정규시즌은 무승부 허용
    max_overtimes_playoffs: int = 99
    timeouts_per_half: int = 3
    timeouts_overtime: int = 2
    scrimmage_touchback_kickoff: int = 35
    two_point_conversions: bool = True
    home_advantage_pct: float = 1.0       # 홈팀 합성 능력 보정 (%)
    base_injury_rate: float = 0.0008      # 선수·플레이당 (F10에서 정교화)
    pace: float = 1.0
    pass_factor: float = 1.0
    fourth_down_factor: float = 1.0
    onside_factor: float = 1.0
    onside_recovery_factor: float = 1.0
    fg_accuracy_factor: float = 1.0
    fumble_factor: float = 1.0
    sack_factor: float = 1.0
    int_factor: float = 1.0
    completion_factor: float = 1.0
    scramble_factor: float = 1.0
    pass_yds_factor: float = 1.0
    rush_yds_factor: float = 1.0
    foul_rate_factor: float = 1.0

    @classmethod
    def from_config(cls) -> "GameSettings":
        try:
            raw = load("league_rules").get("game", {})
        except FileNotFoundError:
            raw = {}
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in names})
