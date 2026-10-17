"""명령줄 도구. 웹 UI(M6) 전까지 리그를 만들고 경기를 돌려보는 용도.

    gridiron fetch-data --season 2026
    gridiron new-game --source real --team KC --save saves/career.sqlite
    gridiron tactics --save saves/career.sqlite                     # 전술·숙련도·궁합 (cli_tactics 참고)
    gridiron gameplan --save saves/career.sqlite                    # 다음 상대 스카우팅 + 이번 주 조정
    gridiron train --save saves/career.sqlite                       # 주간 훈련
    gridiron sim-game --save saves/career.sqlite --team KC --pbp
    gridiron sim-week --save saves/career.sqlite
    gridiron sim-season --save saves/career.sqlite --quiet
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


def _play(path: Path, league: League, game: ScheduledGame, user_team: str | None, pbp: bool, seed: int | None = None):
    from .season.runner import play_game
    return play_game(path, league, game, user_team, pbp, seed)


def cmd_sim_game(args) -> None:
    from .cli_tactics import print_game_tactics
    from .db.store import load_league
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
    out = _play(path, league, game, user_team, True, args.seed)
    from .season.runner import finish_week
    notes = finish_week(path, league, game.week, user_team)
    if args.pbp:
        for line in render_game(out.play_by_play, [game.home, game.away]):
            print(line)
    _print_box(out, league)
    print_game_tactics(out, league, team)
    for n in notes:
        print(n)


def _print_result(user_team: str | None):
    def show(g: ScheduledGame, out) -> None:
        mark = " ◀" if user_team in (g.home, g.away) else ""
        ot = " (OT)" if out.overtimes else ""
        print(f"  {g.away:>3} {out.away_score:>2} @ {g.home:<3} {out.home_score:>2}{ot}{mark}")
    return show


def _week_title(league: League) -> str:
    from .season.runner import ROUND_LABEL
    games = league.games_in_week(league.week)
    kind = games[0].game_type if games else "REG"
    return f"{league.season} 시즌 {league.week}주차" if kind == "REG" else f"{league.season} {ROUND_LABEL[kind]}"


def cmd_sim_week(args) -> None:
    from .db.store import load_league
    from .season.runner import season_over, sim_week
    path = Path(args.save)
    league, user_team = load_league(path)
    if season_over(league):
        sys.exit("시즌이 끝났습니다. (오프시즌은 Post-MVP)")
    print(f"{_week_title(league)} — {sum(not g.played for g in league.games_in_week(league.week))}경기")
    for n in sim_week(path, league, user_team, _print_result(user_team)):
        print(n)


def cmd_sim_season(args) -> None:
    """남은 주를 한 번에 진행한다 (--until regular: 정규시즌 끝까지, end: 슈퍼볼까지)."""
    from .db.store import load_league
    from .season.runner import season_over, sim_week
    path = Path(args.save)
    league, user_team = load_league(path)
    while not season_over(league):
        if args.until == "regular" and league.phase == "playoffs":
            break
        title = _week_title(league)
        if args.quiet:
            def show(g, out, title=title):
                if user_team in (g.home, g.away):
                    print(f"{title}: {g.away} {out.away_score} @ {g.home} {out.home_score}")
        else:
            print(title)
            show = _print_result(user_team)
        for n in sim_week(path, league, user_team, show):
            print(n)
    if season_over(league):
        _print_standings(league, user_team)


def _print_standings(league: League, user_team: str | None) -> None:
    from .season import standings as ST
    st = ST.compute(league)
    seed_of = {t: i + 1 for s in st.seeds.values() for i, t in enumerate(s)}
    for conf in ("AFC", "NFC"):
        for div in ("East", "North", "South", "West"):
            print(f"\n{conf} {div}")
            for t in st.divisions[(conf, div)]:
                r = st.rec(t)
                mark = " ◀" if t == user_team else ""
                seed = f"({seed_of[t]})" if t in seed_of else ""
                print(f"  {seed:>3} {league.teams[t].name:<28} {r.text():>7}  득점 {r.pf:>3} 실점 {r.pa:>3}"
                      f"  디비전 {st.table.rec(t, st.table.div_teams(t) - {t}).text()}{mark}")
    for conf in ("AFC", "NFC"):
        print(f"\n{conf} 플레이오프 시드: " + "  ".join(f"{i + 1}.{t}" for i, t in enumerate(st.seeds[conf])))
    played = [g for g in league.schedule if g.game_type != "REG" and g.played]
    if played:
        from .season.runner import ROUND_LABEL
        print("\n플레이오프")
        for g in played:
            print(f"  {ROUND_LABEL[g.game_type]:<10} {g.away:>3} {g.away_score:>2} @ {g.home:<3} {g.home_score:>2}")
        champ = ST.champion(league)
        if champ:
            print(f"\n🏆 {league.teams[champ].name}")


def cmd_standings(args) -> None:
    from .db.store import load_league
    league, user_team = load_league(Path(args.save))
    _print_standings(league, user_team)


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

    from .cli_tactics import cmd_gameplan, cmd_tactics, cmd_train
    p = sub.add_parser("tactics", help="전술 보기·변경 (PRD F4)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--team")
    p.add_argument("--preset", help="공격+수비 프리셋 (예: west_coast+tampa2)")
    p.add_argument("--set", nargs="+", help="경로=값 (예: offense.run_share=0.45 defense.blitz=1.3)")
    p.add_argument("--situ", nargs="+", help='상황 키와 값 (예: "3l|opp" pass=0.15 blitz=1.5)')
    p.add_argument("--clear-situ", action="store_true")
    p.add_argument("--preview", action="store_true", help="저장하지 않고 궁합 변화만 보기")
    p.set_defaults(func=cmd_tactics)

    p = sub.add_parser("gameplan", help="다음 상대 스카우팅 리포트와 이번 주 게임플랜 (F4-7)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--team")
    p.add_argument("--set", nargs="+")
    p.add_argument("--clear", action="store_true")
    p.set_defaults(func=cmd_gameplan)

    p = sub.add_parser("train", help="주간 훈련 초점·강도와 숙련도 (F11)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--team")
    p.add_argument("--main", help="주 초점 (familiarity:<영역|auto>, opponent, redzone, third_down, two_minute, special, recovery)")
    p.add_argument("--sub", help="보조 초점 (none이면 없음)")
    p.add_argument("--intensity", choices=["light", "normal", "hard"])
    p.set_defaults(func=cmd_train)

    from .cli_season import add_parsers as add_season
    add_season(sub)

    p = sub.add_parser("sim-season", help="남은 시즌을 한 번에 진행 (정규시즌·플레이오프)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--until", choices=["regular", "end"], default="end")
    p.add_argument("--quiet", action="store_true", help="우리 팀 경기만 출력")
    p.set_defaults(func=cmd_sim_season)

    p = sub.add_parser("standings", help="순위표 (공식 타이브레이커·시드)")
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
