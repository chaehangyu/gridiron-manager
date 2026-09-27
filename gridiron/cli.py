"""명령줄 도구 (M0–M1). 웹 UI(M6) 전까지 리그를 만들고 경기를 돌려보는 용도.

    gridiron fetch-data --season 2026
    gridiron new-game --source real --team KC --save saves/career.sqlite
    gridiron sim-game --save saves/career.sqlite --team KC --pbp
    gridiron sim-week --save saves/career.sqlite
    gridiron standings --save saves/career.sqlite
    gridiron quick --home KC --away BUF --pbp
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .domain.models import League, ScheduledGame


def _load_source(source: str, season: int) -> League:
    if source == "sample":
        from .data.sample import generate_sample_league
        return generate_sample_league(season=season)
    from .data.real_league import load_real_league
    return load_real_league(season)


def _seed_for(game: ScheduledGame, base: int = 0) -> int:
    import zlib
    return zlib.crc32(game.game_id.encode()) ^ base


def _print_box(out, league: League) -> None:
    g = out.game
    home, away = league.teams[g.home], league.teams[g.away]
    ot = f" (연장 {out.overtimes})" if out.overtimes else ""
    print(f"\n{away.name} {out.away_score} @ {home.name} {out.home_score}{ot}")
    rows = [("패스", lambda s: f"{s.get('pssCmp', 0)}/{s.get('pss', 0)}, {s.get('pssYds', 0)}yd, TD {s.get('pssTD', 0)}, INT {s.get('pssInt', 0)}"),
            ("러싱", lambda s: f"{s.get('rus', 0)}회 {s.get('rusYds', 0)}yd, TD {s.get('rusTD', 0)}"),
            ("색 허용", lambda s: f"{s.get('pssSk', 0)}"),
            ("턴오버", lambda s: f"{s.get('pssInt', 0) + s.get('fmbLost', 0)}"),
            ("반칙", lambda s: f"{s.get('pen', 0)}개 {s.get('penYds', 0)}yd"),
            ("공격 시간", lambda s: f"{int(s.get('timePos', 0))}:{int(s.get('timePos', 0) % 1 * 60):02d}")]
    print(f"{'':10}{g.away:>28}{g.home:>28}")
    for label, fn in rows:
        print(f"{label:10}{fn(out.box['teams'][g.away]):>28}{fn(out.box['teams'][g.home]):>28}")
    print(f"{'쿼터별':10}{str(out.box['teams'][g.away]['ptsQtrs']):>28}{str(out.box['teams'][g.home]['ptsQtrs']):>28}")
    leaders = []
    for key, label in (("pssYds", "패싱"), ("rusYds", "러싱"), ("recYds", "리시빙"), ("defSk", "색")):
        best = max(out.box["players"].items(), key=lambda kv: kv[1][1].get(key, 0), default=None)
        if best and best[1][1].get(key, 0):
            leaders.append(f"{label}: {league.players[best[0]].name} ({best[1][0]}) {best[1][1][key]}")
    print("주요 기록 — " + " · ".join(leaders))
    if out.wp_series:
        ends = {}
        for q, clock, wp in out.wp_series:
            ends[min(q, 5)] = wp
        path = " → ".join(f"{'Q' + str(q) if q <= 4 else 'OT'} {wp * 100:.0f}%" for q, wp in sorted(ends.items()))
        print(f"{home.nickname} 승률 추이 — {path}")


def cmd_fetch(args) -> None:
    from .data.nflverse_import import fetch
    out = fetch(args.season)
    print(f"저장 완료: {out}")


def cmd_new(args) -> None:
    from .db.store import save_league
    league = _load_source(args.source, args.season)
    if args.team and args.team not in league.teams:
        sys.exit(f"팀 약어 {args.team}가 없습니다. 가능한 값: {', '.join(sorted(league.teams))}")
    save_league(league, Path(args.save), user_team=args.team)
    t = league.teams.get(args.team) if args.team else None
    print(f"새 게임 저장: {args.save} ({league.source}, {league.season} 시즌, 팀 {t.name if t else '-'})")


def cmd_sim_game(args) -> None:
    from .db.store import load_league, record_game
    from .engine.api import simulate
    from .engine.commentary import render_game
    path = Path(args.save)
    league, user_team = load_league(path)
    team = args.team or user_team
    if args.game_id:
        game = next(g for g in league.schedule if g.game_id == args.game_id)
    else:
        week = args.week or league.week
        game = next((g for g in league.games_in_week(week) if team in (g.home, g.away) and not g.played), None)
        if game is None:
            sys.exit(f"{week}주차에 {team}의 남은 경기가 없습니다 (바이위크이거나 이미 치렀습니다).")
    out = simulate(league, game, seed=args.seed if args.seed is not None else _seed_for(game), play_by_play=True)
    if args.pbp:
        for line in render_game(out.play_by_play, [game.home, game.away]):
            print(line)
    _print_box(out, league)
    record_game(path, game, {"overtimes": out.overtimes}, out.seed, out.box)


def cmd_sim_week(args) -> None:
    from .db.store import load_league, record_game, set_week
    from .engine.api import simulate
    path = Path(args.save)
    league, user_team = load_league(path)
    week = args.week or league.week
    games = [g for g in league.games_in_week(week) if not g.played]
    print(f"{league.season} 시즌 {week}주차 — {len(games)}경기")
    for g in games:
        out = simulate(league, g, seed=_seed_for(g), play_by_play=False)
        record_game(path, g, {"overtimes": out.overtimes}, out.seed, out.box)
        mark = " ◀" if user_team in (g.home, g.away) else ""
        ot = " (OT)" if out.overtimes else ""
        print(f"  {g.away:>3} {out.away_score:>2} @ {g.home:<3} {out.home_score:>2}{ot}{mark}")
    if all(g.played for g in league.games_in_week(week)):
        set_week(path, week + 1)


def cmd_standings(args) -> None:
    from .db.store import load_league, standings
    path = Path(args.save)
    league, user_team = load_league(path)
    rows = {r.team: r for r in standings(path, league.season)}
    for conf in ("AFC", "NFC"):
        for div in ("East", "North", "South", "West"):
            teams = [t for t in league.teams.values() if t.conference == conf and t.division == div]
            teams.sort(key=lambda t: (-(rows[t.abbr].wins + 0.5 * rows[t.abbr].ties), -(rows[t.abbr].points_for - rows[t.abbr].points_against)))
            print(f"\n{conf} {div}")
            for t in teams:
                r = rows[t.abbr]
                mark = " ◀" if t.abbr == user_team else ""
                print(f"  {t.name:<28} {f'{r.wins}-{r.losses}-{r.ties}':>7}  득점 {r.points_for:>3} 실점 {r.points_against:>3}{mark}")
    print("\n※ 순위는 승률·득실차 임시 정렬입니다. 공식 타이브레이커(nflseedR 포팅)는 M5에서 적용합니다.")


def cmd_quick(args) -> None:
    from .engine.api import simulate
    from .engine.commentary import render_game
    league = _load_source(args.source, args.season)
    game = ScheduledGame(game_id=f"quick_{args.away}_{args.home}", season=league.season, week=0, game_type="REG",
                         home=args.home, away=args.away, gameday=league.season_start())
    out = simulate(league, game, seed=args.seed if args.seed is not None else 1, play_by_play=True)
    if args.pbp:
        for line in render_game(out.play_by_play, [game.home, game.away]):
            print(line)
    _print_box(out, league)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="gridiron", description="Gridiron Manager 명령줄 도구")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch-data", help="nflverse 실데이터 수집·가공")
    p.add_argument("--season", type=int, default=2026)
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("new-game", help="새 세이브 만들기")
    p.add_argument("--source", choices=["real", "sample"], default="real")
    p.add_argument("--season", type=int, default=2026)
    p.add_argument("--team", help="사용자 팀 약어 (예: KC)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("sim-game", help="한 경기 시뮬레이션 (기본: 사용자 팀의 이번 주 경기)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--team")
    p.add_argument("--week", type=int)
    p.add_argument("--game-id")
    p.add_argument("--seed", type=int)
    p.add_argument("--pbp", action="store_true", help="텍스트 중계 출력")
    p.set_defaults(func=cmd_sim_game)

    p = sub.add_parser("sim-week", help="이번 주 남은 경기 전부 시뮬레이션")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--week", type=int)
    p.set_defaults(func=cmd_sim_week)

    p = sub.add_parser("standings", help="순위표")
    p.add_argument("--save", default="saves/career.sqlite")
    p.set_defaults(func=cmd_standings)

    p = sub.add_parser("quick", help="저장 없이 두 팀 경기 한 번")
    p.add_argument("--home", required=True)
    p.add_argument("--away", required=True)
    p.add_argument("--source", choices=["real", "sample"], default="real")
    p.add_argument("--season", type=int, default=2026)
    p.add_argument("--seed", type=int)
    p.add_argument("--pbp", action="store_true")
    p.set_defaults(func=cmd_quick)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except BrokenPipeError:  # `| head` 등으로 출력이 잘린 경우
        sys.stderr.close()


if __name__ == "__main__":
    main()
