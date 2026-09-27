"""세이브 파일 스키마 (PRD §7.3, SQLite + SQLModel).

원칙
- 선수 고유 ID = nflverse gsis_id (샘플 리그는 SMP-xxxxx).
- 능력치·기록·팀 성적은 시즌(필요하면 주차)별 행으로 쌓는다. 덮어쓰지 않는다.
- 아직 로직이 없는 테이블(계약, 훈련, 구단주, 스카우팅 등)도 지금 정의해 두어 이후 마이그레이션을 줄인다.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

SCHEMA_VERSION = 1


def JsonField(default_factory: Any = dict) -> Any:  # noqa: N802
    return Field(default_factory=default_factory, sa_column=Column(JSON))


class LeagueRow(SQLModel, table=True):
    __tablename__ = "league"
    id: int = Field(default=1, primary_key=True)
    schema_version: int = SCHEMA_VERSION
    season: int
    week: int = 1
    phase: str = "regular"          # preseason | regular | playoffs | draft | resign | free_agency
    source: str = "sample"          # sample | nflverse
    user_team: Optional[str] = None
    created_at: Optional[str] = None


class TeamRow(SQLModel, table=True):
    __tablename__ = "team"
    abbr: str = Field(primary_key=True)
    city: str
    nickname: str
    conference: str
    division: str
    color: str
    color2: str
    front: str


class TeamSeasonRow(SQLModel, table=True):
    __tablename__ = "team_season"
    team: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: int = 0
    points_against: int = 0
    playoff_result: Optional[str] = None
    tactics: dict = JsonField(default_factory=dict)


class PlayerRow(SQLModel, table=True):
    __tablename__ = "player"
    id: str = Field(primary_key=True)
    name: str
    position: str
    team: Optional[str] = Field(default=None, index=True)
    roster_status: str = "active"   # active | practice_squad | ir | fa | retired
    birth_date: Optional[date] = None
    height_in: Optional[int] = None
    weight_lb: Optional[int] = None
    college: Optional[str] = None
    jersey: Optional[int] = None
    years_exp: int = 0
    draft_year: Optional[int] = None
    draft_round: Optional[int] = None
    draft_pick: Optional[int] = None
    draft_team: Optional[str] = None
    condition: float = 100.0
    ps_elevations_used: int = 0


class PlayerRatingsRow(SQLModel, table=True):
    """능력치 이력. 시즌 중 부상·성장 변화도 새 행으로 쌓는다."""

    __tablename__ = "player_ratings"
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)
    season: int
    week: int = 0
    attributes: dict = JsonField(default_factory=dict)
    source: str = "provisional"      # provisional | pipeline | manual | sample


class DepthChartRow(SQLModel, table=True):
    __tablename__ = "depth_chart"
    team: str = Field(primary_key=True)
    slot: str = Field(primary_key=True)
    order: int = Field(primary_key=True)
    player_id: str
    role: Optional[str] = None


class GameRow(SQLModel, table=True):
    __tablename__ = "game"
    id: str = Field(primary_key=True)
    season: int = Field(index=True)
    week: int = Field(index=True)
    game_type: str = "REG"
    home: str
    away: str
    gameday: Optional[date] = None
    stadium: Optional[str] = None
    roof: Optional[str] = None
    surface: Optional[str] = None
    neutral_site: bool = False
    seed: Optional[int] = None
    status: str = "scheduled"        # scheduled | final
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    overtimes: int = 0


class TeamGameStatsRow(SQLModel, table=True):
    __tablename__ = "team_game_stats"
    game_id: str = Field(primary_key=True)
    team: str = Field(primary_key=True)
    stats: dict = JsonField(default_factory=dict)


class PlayerGameStatsRow(SQLModel, table=True):
    __tablename__ = "player_game_stats"
    game_id: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    team: str
    stats: dict = JsonField(default_factory=dict)


class PlayerSeasonStatsRow(SQLModel, table=True):
    __tablename__ = "player_season_stats"
    player_id: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    team: str = Field(primary_key=True)
    is_playoffs: bool = Field(default=False, primary_key=True)
    stats: dict = JsonField(default_factory=dict)


class PlayRow(SQLModel, table=True):
    """플레이 로그 (PRD F5-5d, ENGINE_DESIGN §8). M2부터 결과 모델 기여분까지 기록."""

    __tablename__ = "play"
    game_id: str = Field(primary_key=True)
    seq: int = Field(primary_key=True)
    event: dict = JsonField(default_factory=dict)


# ── 이후 단계용 (구조만 먼저) ──────────────────────────────────────────
class ContractRow(SQLModel, table=True):
    __tablename__ = "contract"
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)
    team: str
    start_season: int
    end_season: int
    apy: Optional[float] = None
    guaranteed: Optional[float] = None
    source: str = "otc"


class TacticsRow(SQLModel, table=True):
    __tablename__ = "tactics"
    team: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    layer: str = Field(primary_key=True)   # base | situational | gameplan
    week: int = Field(default=0, primary_key=True)
    payload: dict = JsonField(default_factory=dict)


class InjuryRow(SQLModel, table=True):
    __tablename__ = "injury"
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)
    game_id: Optional[str] = None
    body_part: str
    type: str
    severity: str
    diagnosed_min_weeks: int
    diagnosed_max_weeks: int
    actual_weeks: int
    status: str = "out"
    reinjury_risk_until_week: Optional[int] = None


class PracticeReportRow(SQLModel, table=True):
    __tablename__ = "practice_report"
    player_id: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    week: int = Field(primary_key=True)
    day: str = Field(primary_key=True)     # wed | thu | fri
    participation: str                     # dnp | limited | full


class IRDesignationRow(SQLModel, table=True):
    __tablename__ = "ir_designation"
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: str
    season: int
    placed_week: int
    eligible_week: int
    designated_to_return: bool = False


class TransactionRow(SQLModel, table=True):
    __tablename__ = "transaction"
    id: Optional[int] = Field(default=None, primary_key=True)
    season: int
    week: int
    team: str
    player_id: str
    type: str                              # sign | release | elevate | promote | ir | trade


class FamiliarityRow(SQLModel, table=True):
    __tablename__ = "familiarity"
    id: Optional[int] = Field(default=None, primary_key=True)
    team: str
    player_id: Optional[str] = None        # None = 팀 전체
    season: int
    week: int
    dimension: str
    value: float


class TrainingPlanRow(SQLModel, table=True):
    __tablename__ = "training_plan"
    team: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    week: int = Field(primary_key=True)
    main_focus: str
    sub_focus: Optional[str] = None
    intensity: str = "normal"
    group_overrides: dict = JsonField(default_factory=dict)


class OwnerExpectationRow(SQLModel, table=True):
    __tablename__ = "owner_expectation"
    team: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    tier: str
    projected_wins_mean: float
    projected_wins_sd: float
    main_goal: str
    sub_goals: list = JsonField(default_factory=list)


class OwnerConfidenceRow(SQLModel, table=True):
    __tablename__ = "owner_confidence"
    team: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    week: int = Field(primary_key=True)
    value: float
    reason: Optional[str] = None


class OwnerReviewRow(SQLModel, table=True):
    __tablename__ = "owner_review"
    team: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    grade: str
    fired: bool = False


class ScoutKnowledgeRow(SQLModel, table=True):
    __tablename__ = "scout_knowledge"
    observer_team: str = Field(primary_key=True)
    player_id: str = Field(primary_key=True)
    value: float
    error_seed: int


class ScoutAssignmentRow(SQLModel, table=True):
    __tablename__ = "scout_assignment"
    team: str = Field(primary_key=True)
    season: int = Field(primary_key=True)
    week: int = Field(primary_key=True)
    scout_no: int = Field(primary_key=True)
    target_type: str                       # next_opponent | free_agents | position
    target: Optional[str] = None


class OpponentModelRow(SQLModel, table=True):
    __tablename__ = "opponent_model"
    game_id: str = Field(primary_key=True)
    observer_team: str = Field(primary_key=True)
    bucket: str = Field(primary_key=True)
    family_counts: dict = JsonField(default_factory=dict)
