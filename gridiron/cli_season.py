"""시즌 운영 명령 (M5): 부상 관리.

    gridiron injuries --save s.sqlite                  # 우리 팀 부상 리포트
    gridiron injuries --save s.sqlite --team BUF       # 상대 팀 공식 리포트 (리그 전체 공개)
    gridiron injuries --save s.sqlite --sit <id>       # Questionable 선수 이번 주 휴식 (--play로 되돌림)
    gridiron injuries --save s.sqlite --ir <id>        # IR 등재
    gridiron injuries --save s.sqlite --activate <id>  # IR 복귀 지정
"""
from __future__ import annotations

import sys
from pathlib import Path


def _find(league, team: str, key: str):
    cands = [p for p in league.players.values() if p.team == team and (p.id == key or key.lower() in p.name.lower())]
    if len(cands) != 1:
        sys.exit(f"선수 '{key}'를 하나로 특정할 수 없습니다 ({len(cands)}명)")
    return cands[0]


def cmd_injuries(args) -> None:
    from .db.store import load_league, save_team_state
    from .domain.models import RosterStatus
    from .season import injuries as INJ
    path = Path(args.save)
    league, user_team = load_league(path)
    team = args.team or user_team
    if any((args.sit, args.play, args.ir, args.activate)):
        if team != user_team:
            sys.exit("다른 팀 선수는 관리할 수 없습니다.")
        if args.sit or args.play:
            p = _find(league, team, args.sit or args.play)
            if p.injury is None or p.injury.weeks_remaining > 0:
                sys.exit("출전 여부는 Questionable(결장 기간이 끝난) 선수만 정할 수 있습니다.")
            p.injury.sit = bool(args.sit)
            print(f"{p.name}: 이번 주 {'휴식' if args.sit else '출전'}")
        if args.ir:
            p = _find(league, team, args.ir)
            if p.roster_status != RosterStatus.ACTIVE or p.injury is None:
                sys.exit("부상 중인 53인 로스터 선수만 IR에 올릴 수 있습니다.")
            INJ.place_ir(league, p, league.week - 1 if league.week > 1 else 0)
            print(f"{p.name} IR 등재 — 최소 {INJ.rules()['min_games']}경기 후 복귀 지정 가능")
        if args.activate:
            p = _find(league, team, args.activate)
            ok, why = INJ.can_activate(league, p, league.week)
            if not ok:
                sys.exit(f"복귀 불가: {why}")
            INJ.activate(league, p, league.week)
            used = league.ir_returns_used.get(team, 0)
            print(f"{p.name} IR 복귀 (복귀 지정 {used}/{INJ.rules()['return_designations']})")
        save_team_state(path, league)
    rows = INJ.report_rows(league, team)
    print(f"\n{league.teams[team].name} 부상 리포트 — {league.season} 시즌 {league.week}주차")
    if not rows:
        print("  부상자 없음")
    for r in rows:
        tag = " [IR]" if r["ir"] else (" [휴식 결정]" if r["sit"] else "")
        print(f"  {r['pos']:<3} {r['name']:<22} {r['injury']:<14} {r['status']:<6} 훈련 {r['practice']:<3} "
              f"예상 {r['range']:<10} 결장 {r['missed']}경기{tag}")
    if team == user_team:
        used = league.ir_returns_used.get(team, 0)
        print(f"\nIR 복귀 지정 {used}/{INJ.rules()['return_designations']}회 사용")


def add_parsers(sub) -> None:
    p = sub.add_parser("injuries", help="부상 리포트·출전 결정·IR 관리 (F10)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--team")
    p.add_argument("--sit", help="Questionable 선수 이번 주 휴식 (id 또는 이름)")
    p.add_argument("--play", help="휴식 결정 취소")
    p.add_argument("--ir", help="IR 등재")
    p.add_argument("--activate", help="IR 복귀 지정")
    p.set_defaults(func=cmd_injuries)
