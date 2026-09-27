"""리그·팀·선수 도메인 모델 (메모리 표현).

DB 스키마(`gridiron.db.schema`)와 분리해 두어, 엔진과 테스트가 DB 없이도 동작하게 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .attributes import ATTR_KEYS, clamp
from .positions import Front, Position, all_slots


class RosterStatus(str, Enum):
    ACTIVE = "active"            # 53인 로스터
    PRACTICE_SQUAD = "practice_squad"
    IR = "ir"
    FREE_AGENT = "fa"
    RETIRED = "retired"


@dataclass
class Injury:
    body_part: str
    type: str
    severity: str
    weeks_out_min: int
    weeks_out_max: int
    weeks_remaining: int
    status: str = "out"  # out | doubtful | questionable | healthy


@dataclass
class Player:
    id: str
    name: str
    position: Position
    attributes: dict[str, float]
    birth_date: date | None = None
    height_in: int | None = None
    weight_lb: int | None = None
    college: str | None = None
    jersey: int | None = None
    years_exp: int = 0
    draft_year: int | None = None
    draft_round: int | None = None
    draft_pick: int | None = None
    draft_team: str | None = None
    team: str | None = None
    roster_status: RosterStatus = RosterStatus.ACTIVE
    condition: float = 100.0   # 주간 컨디션 0–100
    injury: Injury | None = None
    ratings_source: str = "provisional"  # provisional | pipeline | manual

    def __post_init__(self) -> None:
        missing = [k for k in ATTR_KEYS if k not in self.attributes]
        if missing:
            raise ValueError(f"{self.id}: 능력치 누락 {missing[:5]}")
        self.attributes = {k: clamp(float(self.attributes[k])) for k in ATTR_KEYS}

    def age_on(self, day: date) -> float:
        if self.birth_date is None:
            return 26.0
        return (day - self.birth_date).days / 365.25

    @property
    def injured(self) -> bool:
        return self.injury is not None and self.injury.weeks_remaining > 0


@dataclass
class Team:
    abbr: str
    city: str
    nickname: str
    conference: str   # AFC | NFC
    division: str     # East | North | South | West
    color: str = "#444444"
    color2: str = "#999999"
    front: Front = Front.FOUR_THREE
    # 슬롯 → 선수 id 순번 목록 (0번이 주전)
    depth_chart: dict[str, list[str]] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.city} {self.nickname}"

    def ensure_slots(self) -> None:
        for slot in all_slots(self.front):
            self.depth_chart.setdefault(slot, [])


@dataclass
class ScheduledGame:
    game_id: str
    season: int
    week: int
    game_type: str      # REG | WC | DIV | CON | SB
    home: str
    away: str
    gameday: date | None = None
    stadium: str | None = None
    roof: str | None = None       # outdoors | dome | closed | open
    surface: str | None = None    # grass | fieldturf | ...
    neutral_site: bool = False
    home_score: int | None = None
    away_score: int | None = None

    @property
    def played(self) -> bool:
        return self.home_score is not None


@dataclass
class League:
    season: int
    teams: dict[str, Team]
    players: dict[str, Player]
    schedule: list[ScheduledGame] = field(default_factory=list)
    week: int = 1
    phase: str = "regular"
    source: str = "sample"  # sample | nflverse

    def roster(self, abbr: str, statuses: tuple[RosterStatus, ...] = (RosterStatus.ACTIVE,)) -> list[Player]:
        return [p for p in self.players.values() if p.team == abbr and p.roster_status in statuses]

    def free_agents(self) -> list[Player]:
        return [p for p in self.players.values() if p.roster_status == RosterStatus.FREE_AGENT]

    def season_start(self) -> date:
        days = [g.gameday for g in self.schedule if g.gameday is not None]
        return min(days) if days else date(self.season, 9, 10)

    def games_in_week(self, week: int) -> list[ScheduledGame]:
        return [g for g in self.schedule if g.week == week]
