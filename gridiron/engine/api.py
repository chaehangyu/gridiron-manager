"""경기 실행 진입점: 리그의 한 경기를 시뮬레이션하고 박스스코어를 만든다."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.models import League, ScheduledGame
from .adapter import build_team
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


def simulate(league: League, game: ScheduledGame, seed: int, *, outcome: OutcomeModel | None = None,
             settings: GameSettings | None = None, play_by_play: bool = True) -> GameOutcome:
    day = game.gameday or league.season_start()
    home = build_team(league, game.home, 0, day)
    away = build_team(league, game.away, 1, day)
    sim = GameSim([home, away], settings=settings or GameSettings.from_config(), outcome=outcome, seed=seed,
                  do_play_by_play=play_by_play, playoffs=game.game_type != "REG", neutral_site=game.neutral_site,
                  gid=game.game_id)
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
    return GameOutcome(game=game, seed=seed, home_score=game.home_score, away_score=game.away_score,
                       overtimes=res["overtimes"], box={"teams": teams, "players": players, "plays": events},
                       play_by_play=res["playByPlay"], scoring_summary=res["scoringSummary"])
