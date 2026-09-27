"""세이브 슬롯 저장·불러오기 (PRD F9). 슬롯 하나 = SQLite 파일 하나."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete
from sqlmodel import Session, SQLModel, create_engine, select

from ..domain.models import League, Player, RosterStatus, ScheduledGame, Team
from ..domain.positions import Front, Position
from . import schema as S


def engine_for(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}")


def save_league(league: League, path: Path, user_team: str | None = None) -> None:
    """리그 전체를 새 세이브로 쓴다 (기존 파일은 덮어쓴다)."""
    if path.exists():
        path.unlink()
    eng = engine_for(path)
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(S.LeagueRow(season=league.season, week=league.week, phase=league.phase, source=league.source,
                          user_team=user_team, created_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
        for t in league.teams.values():
            s.add(S.TeamRow(abbr=t.abbr, city=t.city, nickname=t.nickname, conference=t.conference,
                            division=t.division, color=t.color, color2=t.color2, front=t.front.value))
            s.add(S.TeamSeasonRow(team=t.abbr, season=league.season))
            for slot, ids in t.depth_chart.items():
                for i, pid in enumerate(ids):
                    s.add(S.DepthChartRow(team=t.abbr, slot=slot, order=i, player_id=pid))
        for p in league.players.values():
            s.add(S.PlayerRow(id=p.id, name=p.name, position=p.position.value, team=p.team,
                              roster_status=p.roster_status.value, birth_date=p.birth_date, height_in=p.height_in,
                              weight_lb=p.weight_lb, college=p.college, jersey=p.jersey, years_exp=p.years_exp,
                              draft_year=p.draft_year, draft_round=p.draft_round, draft_pick=p.draft_pick,
                              draft_team=p.draft_team, condition=p.condition))
            s.add(S.PlayerRatingsRow(player_id=p.id, season=league.season, week=0,
                                     attributes={k: round(v, 3) for k, v in p.attributes.items()},
                                     source=p.ratings_source))
        for g in league.schedule:
            s.add(S.GameRow(id=g.game_id, season=g.season, week=g.week, game_type=g.game_type, home=g.home,
                            away=g.away, gameday=g.gameday, stadium=g.stadium, roof=g.roof, surface=g.surface,
                            neutral_site=g.neutral_site, home_score=g.home_score, away_score=g.away_score,
                            status="final" if g.played else "scheduled"))
        s.commit()


def load_league(path: Path) -> tuple[League, str | None]:
    if not path.exists():
        raise FileNotFoundError(path)
    eng = engine_for(path)
    with Session(eng) as s:
        meta = s.exec(select(S.LeagueRow)).one()
        if meta.schema_version != S.SCHEMA_VERSION:
            raise RuntimeError(f"세이브 스키마 버전 {meta.schema_version} ≠ {S.SCHEMA_VERSION} (마이그레이션 필요)")
        teams = {r.abbr: Team(abbr=r.abbr, city=r.city, nickname=r.nickname, conference=r.conference,
                              division=r.division, color=r.color, color2=r.color2, front=Front(r.front))
                 for r in s.exec(select(S.TeamRow))}
        for r in s.exec(select(S.DepthChartRow).order_by(S.DepthChartRow.team, S.DepthChartRow.slot,
                                                         S.DepthChartRow.order)):
            teams[r.team].depth_chart.setdefault(r.slot, []).append(r.player_id)
        latest: dict[str, S.PlayerRatingsRow] = {}
        for r in s.exec(select(S.PlayerRatingsRow).order_by(S.PlayerRatingsRow.season, S.PlayerRatingsRow.week,
                                                            S.PlayerRatingsRow.id)):
            latest[r.player_id] = r
        players = {}
        for r in s.exec(select(S.PlayerRow)):
            rt = latest[r.id]
            players[r.id] = Player(id=r.id, name=r.name, position=Position(r.position), attributes=dict(rt.attributes),
                                   birth_date=r.birth_date, height_in=r.height_in, weight_lb=r.weight_lb,
                                   college=r.college, jersey=r.jersey, years_exp=r.years_exp, draft_year=r.draft_year,
                                   draft_round=r.draft_round, draft_pick=r.draft_pick, draft_team=r.draft_team,
                                   team=r.team, roster_status=RosterStatus(r.roster_status), condition=r.condition,
                                   ratings_source=rt.source)
        schedule = [ScheduledGame(game_id=r.id, season=r.season, week=r.week, game_type=r.game_type, home=r.home,
                                  away=r.away, gameday=r.gameday, stadium=r.stadium, roof=r.roof, surface=r.surface,
                                  neutral_site=r.neutral_site, home_score=r.home_score, away_score=r.away_score)
                    for r in s.exec(select(S.GameRow).order_by(S.GameRow.week, S.GameRow.gameday, S.GameRow.id))]
        league = League(season=meta.season, teams=teams, players=players, schedule=schedule, week=meta.week,
                        phase=meta.phase, source=meta.source)
        return league, meta.user_team


def record_game(path: Path, game: ScheduledGame, result: dict, seed: int, box: dict) -> None:
    """경기 결과, 팀·선수 경기 기록, 플레이 로그를 저장하고 팀 시즌 성적을 갱신한다."""
    eng = engine_for(path)
    with Session(eng) as s:
        row = s.get(S.GameRow, game.game_id)
        row.home_score, row.away_score = game.home_score, game.away_score
        row.status, row.seed, row.overtimes = "final", seed, result["overtimes"]
        s.add(row)
        for model in (S.TeamGameStatsRow, S.PlayerGameStatsRow, S.PlayRow):
            s.exec(delete(model).where(model.game_id == game.game_id))
        for abbr, stats in box["teams"].items():
            s.add(S.TeamGameStatsRow(game_id=game.game_id, team=abbr, stats=stats))
        for pid, (abbr, stats) in box["players"].items():
            s.add(S.PlayerGameStatsRow(game_id=game.game_id, player_id=pid, team=abbr, stats=stats))
        for i, ev in enumerate(box.get("plays", [])):
            s.add(S.PlayRow(game_id=game.game_id, seq=i, event=ev))
        if game.game_type == "REG":
            for abbr, pf, pa in ((game.home, game.home_score, game.away_score),
                                 (game.away, game.away_score, game.home_score)):
                ts = s.get(S.TeamSeasonRow, (abbr, game.season)) or S.TeamSeasonRow(team=abbr, season=game.season)
                ts.points_for += pf
                ts.points_against += pa
                if pf > pa:
                    ts.wins += 1
                elif pf < pa:
                    ts.losses += 1
                else:
                    ts.ties += 1
                s.add(ts)
        s.commit()


def set_week(path: Path, week: int) -> None:
    eng = engine_for(path)
    with Session(eng) as s:
        meta = s.exec(select(S.LeagueRow)).one()
        meta.week = week
        s.add(meta)
        s.commit()


def standings(path: Path, season: int) -> list[S.TeamSeasonRow]:
    eng = engine_for(path)
    with Session(eng) as s:
        return list(s.exec(select(S.TeamSeasonRow).where(S.TeamSeasonRow.season == season)))
