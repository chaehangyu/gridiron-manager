"""경기 실행 진입점: 리그의 한 경기를 시뮬레이션하고 박스스코어를 만든다."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.models import League, ScheduledGame
from .adapter import build_team
from .norms import compute_norms
from .outcome.base import OutcomeModel
from .skeleton.game import GameSim
from .skeleton.settings import GameSettings

_DROP = {"energy", "courtTime", "benchTime"}


def _clean(stats: dict) -> dict:
    out = {}
    for k, v in stats.items():
        if k in _DROP:
            continue
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        elif isinstance(v, float):
            v = round(v, 3)
        out[k] = v
    return out


@dataclass
class GameOutcome:
    game: ScheduledGame
    seed: int
    home_score: int
    away_score: int
    overtimes: int
    box: dict
    play_by_play: list[dict] = field(default_factory=list)
    scoring_summary: list[dict] = field(default_factory=list)
    wp_series: list[tuple] = field(default_factory=list)
    tactics: dict = field(default_factory=dict)     # 팀별 전술 리포트 (DataOutcome.report)


def prepare_teams(league: League, game: ScheduledGame, user_team: str | None = None):
    """경기용 두 팀: 이번 주 전술(게임플랜 포함)·숙련도·훈련 준비값 + 상대에 대한 스카우팅 사전값 (M4)."""
    from ..tactics.scouting import prior

    day = game.gameday or league.season_start()
    home = build_team(league, game.home, 0, day, week=game.week, ai_controlled=game.home != user_team)
    away = build_team(league, game.away, 1, day, week=game.week, ai_controlled=game.away != user_team)
    for me, opp in ((home, away), (away, home)):
        mt, ot = league.teams[me.abbr], league.teams[opp.abbr]
        me.scout = prior(ot.scouting or None, ot.last_tendency, league.league_tendency,
                         scout_add=mt.prep.get("scout_add", 0.0))
    return home, away


def simulate(league: League, game: ScheduledGame, seed: int, *, outcome: OutcomeModel | None = None,
             settings: GameSettings | None = None, play_by_play: bool = True,
             user_team: str | None = None) -> GameOutcome:
    home, away = prepare_teams(league, game, user_team)
    if outcome is None:
        from .outcome.data_model import DataOutcome
        outcome = DataOutcome.for_league(league, explain=play_by_play)
    sim = GameSim([home, away], settings=settings or GameSettings.from_config(), outcome=outcome, seed=seed,
                  do_play_by_play=play_by_play, playoffs=game.game_type != "REG", neutral_site=game.neutral_site,
                  gid=game.game_id, venue={"roof": game.roof, "surface": game.surface},
                  norms=compute_norms(league))
    res = sim.run()
    teams = {t.abbr: _clean(t.stat) for t in res["team"]}
    players = {}
    for t in res["team"]:
        for p in t.players:
            st = _clean(p.stat)
            if st.get("gp"):
                players[p.id] = (t.abbr, st)
    game.home_score = int(res["team"][0].stat["pts"])
    game.away_score = int(res["team"][1].stat["pts"])
    events = [e for e in res["playByPlay"] if e["type"] != "clock"] if play_by_play else []
    tactics = outcome.report() if hasattr(outcome, "report") else {}
    return GameOutcome(game=game, seed=seed, home_score=game.home_score, away_score=game.away_score,
                       overtimes=res["overtimes"], box={"teams": teams, "players": players, "plays": events},
                       play_by_play=res["playByPlay"], scoring_summary=res["scoringSummary"], wp_series=sim.wp_series,
                       tactics=tactics)
