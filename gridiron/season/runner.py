"""시즌 진행 (PRD §4 핵심 루프, F1, M5).

경기 하나: 주간 준비 → 시뮬 → 저장 → 주간 상태 갱신.
주 마감: 모든 경기가 끝나면 다음 주로. 정규시즌·각 라운드가 끝나면 플레이오프 대진을 만들고, 슈퍼볼 뒤 시즌 종료.
"""
from __future__ import annotations

import zlib
from pathlib import Path
from typing import Callable

from ..domain.models import League, ScheduledGame
from . import standings
from .weekly import after_game, prepare_week

ROUND_LABEL = {"REG": "정규시즌", "WC": "와일드카드", "DIV": "디비저널", "CON": "컨퍼런스 챔피언십", "SB": "슈퍼볼",
               "CHAMP": "우승"}


def seed_for(game: ScheduledGame, base: int = 0) -> int:
    return zlib.crc32(game.game_id.encode()) ^ base


def play_game(path: Path, league: League, game: ScheduledGame, user_team: str | None, pbp: bool = False,
              seed: int | None = None):
    from ..db.store import record_game, save_team_state
    from ..engine.api import simulate
    prepare_week(league, game.week)
    out = simulate(league, game, seed=seed if seed is not None else seed_for(game), play_by_play=pbp,
                   user_team=user_team)
    record_game(path, game, {"overtimes": out.overtimes}, out.seed, out.box, tactics=out.tactics)
    after_game(league, out.tactics, out.box["players"])
    save_team_state(path, league)
    return out


def finish_week(path: Path, league: League, week: int) -> list[str]:
    """이번 주 경기가 모두 끝났으면 다음 단계로 넘긴다. 사용자에게 보여줄 알림을 돌려준다."""
    from ..db.store import add_games, set_playoff_results, set_progress
    games = league.games_in_week(week)
    if not games or not all(g.played for g in games):
        return []
    notes: list[str] = []
    new = standings.next_round(league)
    if new:
        league.schedule.extend(new)
        add_games(path, new)
        league.phase = "playoffs"
        rnd = new[0].game_type
        if rnd == "WC":
            st = standings.compute(league)
            for conf in ("AFC", "NFC"):
                notes.append(f"{conf} 시드: " + ", ".join(f"{i + 1} {t}" for i, t in enumerate(st.seeds[conf])))
        notes.append(f"{ROUND_LABEL[rnd]} 대진: " + ", ".join(f"{g.away} @ {g.home}" for g in new))
    elif standings.champion(league):
        league.phase = "offseason"
        set_playoff_results(path, league.season, standings.eliminated_round(league))
        notes.append(f"{league.season} 시즌 종료 — 우승 {league.teams[standings.champion(league)].name}")
    league.week = week + 1 if league.phase != "offseason" else week
    set_progress(path, week=league.week, phase=league.phase)
    return notes


def sim_week(path: Path, league: League, user_team: str | None,
             on_game: Callable[[ScheduledGame, object], None] | None = None) -> list[str]:
    week = league.week
    for g in [g for g in league.games_in_week(week) if not g.played]:
        out = play_game(path, league, g, user_team)
        if on_game:
            on_game(g, out)
    return finish_week(path, league, week)


def season_over(league: League) -> bool:
    return league.phase == "offseason"
