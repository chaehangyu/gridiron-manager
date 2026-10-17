"""리그·팀·선수 도메인 모델 (메모리 표현).

DB 스키마(`gridiron.db.schema`)와 분리해 두어, 엔진과 테스트가 DB 없이도 동작하게 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .attributes import ATTR_KEYS, clamp
from .positions import Front, Position, all_slots


def _tactics():
    from ..tactics.model import Tactics
    return Tactics()


def _familiarity():
    from ..tactics.familiarity import default
    return default()


def _training():
    from ..tactics.training import TrainingPlan
    return TrainingPlan()


class RosterStatus(str, Enum):
    ACTIVE = "active"            # 53인 로스터
    PRACTICE_SQUAD = "practice_squad"
    IR = "ir"
    FREE_AGENT = "fa"
    RETIRED = "retired"


@dataclass
class Injury:
    body_part: str
    type: str                 # 표시 이름 (예: 발목 염좌)
    severity: str
    weeks_out_min: int        # 진단 범위 (사용자에게 보이는 값)
    weeks_out_max: int
    weeks_remaining: int      # 실제 남은 결장 경기 수 (숨김). 99 = 시즌 아웃
    status: str = "out"       # out | doubtful | questionable | healthy (주간 공식 리포트)
    season: int = 0
    week: int = 0             # 다친 주
    game_id: str | None = None
    missed: int = 0           # 지금까지 결장한 경기 수
    practice: str = "full"    # 이번 주 훈련 참여: dnp | limited | full
    sit: bool = False         # Questionable이어도 쉬게 함 (사용자 결정)
    id: int | None = None     # 세이브 행 id


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
    ratings_source: str = "provisional"  # provisional | measured:measured | measured:prior | sample
    # ── 부상 이력·복귀 관리 (F10-6, M5b) ──
    reinjury_until: int = 0        # 이 주까지 재부상 위험 증가 (같은 시즌 주차)
    rust_games: int = 0            # 남은 경기 감각 페널티 경기 수
    ir_week: int | None = None     # IR 등재 주
    concussions: int = 0           # 이번 시즌 뇌진탕 횟수
    elevations: int = 0            # 이번 시즌 연습 스쿼드 임시 승격 횟수 (F3-8b)

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
        """이번 주 경기에 못 나간다 (결장 중이거나 Questionable인데 쉬게 함)."""
        return self.injury is not None and (self.injury.weeks_remaining > 0 or self.injury.sit)

    @property
    def hurt(self) -> bool:
        """부상을 안고 뛴다 (Questionable 강행)."""
        return self.injury is not None and not self.injured


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
    # ── 전술·주간 준비 (PRD F4·F11, M4) ──
    tactics: "Tactics" = field(default_factory=lambda: _tactics())
    gameplan: dict = field(default_factory=dict)          # 이번 주 게임플랜 (부분 덮어쓰기)
    gameplan_week: int | None = None
    familiarity: dict[str, float] = field(default_factory=lambda: _familiarity())
    training: "TrainingPlan" = field(default_factory=lambda: _training())
    prep: dict = field(default_factory=dict)              # 이번 주 훈련이 만든 경기 준비값
    usage: dict[str, float] = field(default_factory=dict)  # 최근 경기 영역 사용량 (숙련도 감소 판단)
    scouting: dict = field(default_factory=dict)          # 이번 시즌 콜 성향 누적 (상대가 본다)
    last_tendency: dict | None = None                     # 지난 시즌 실측 성향
    # ── 로스터 운영 (F3, M5c) ──
    elevated: list[str] = field(default_factory=list)     # 이번 주 연습 스쿼드 임시 승격
    inactives: list[str] = field(default_factory=list)    # 사용자 지정 비활성 (경기 당일 48인에서 제외)
    auto_roster: bool = True                              # 대체 영입·임시 승격 자동 (스태프 권고)

    def tactics_for_week(self, week: int) -> "Tactics":
        return self.tactics.merged(self.gameplan if self.gameplan_week == week else None)

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
    league_tendency: dict | None = None   # 지난 시즌 리그 평균 성향 (team_tendencies.json의 league)
    prepared_week: int = 0                # 주간 훈련을 적용한 마지막 주
    ir_returns_used: dict[str, int] = field(default_factory=dict)   # 팀 → 이번 시즌 IR 복귀 지정 횟수
    owner: object = None                  # 사용자 팀 구단주 상태 (season.owner.OwnerState, M5d)
    knowledge: dict[str, float] = field(default_factory=dict)   # 사용자 팀의 선수 파악도 (기본값과 다른 것만, F13)
    scout_assignments: list[str] = field(default_factory=list)  # 스카우트 3명 배정 (F13-3)

    def roster(self, abbr: str, statuses: tuple[RosterStatus, ...] = (RosterStatus.ACTIVE,)) -> list[Player]:
        return [p for p in self.players.values() if p.team == abbr and p.roster_status in statuses]

    def free_agents(self) -> list[Player]:
        return [p for p in self.players.values() if p.roster_status == RosterStatus.FREE_AGENT]

    def season_start(self) -> date:
        days = [g.gameday for g in self.schedule if g.gameday is not None]
        return min(days) if days else date(self.season, 9, 10)

    def games_in_week(self, week: int) -> list[ScheduledGame]:
        return [g for g in self.schedule if g.week == week]
