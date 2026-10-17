"""시즌 운영 명령 (M5): 부상 관리, 로스터 운영.

    gridiron roster --save s.sqlite                    # 53인·연습 스쿼드·IR, 경기 당일 48인
    gridiron roster --save s.sqlite --auto off         # 대체 영입·임시 승격 자동 관리 끄기
    gridiron roster --save s.sqlite --release <id> | --promote <id> | --demote <id> | --elevate <id>
    gridiron roster --save s.sqlite --inactive <id> | --activate-gameday <id>
    gridiron fa --save s.sqlite --pos WR               # FA 풀 (PR 순)
    gridiron fa --save s.sqlite --sign <id> [--ps]     # 최저 연봉 1년 계약

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


def cmd_roster(args) -> None:
    from .db.store import load_league, record_transactions, save_team_state
    from .ratings.position_rating import position_rating
    from .season import roster as R
    path = Path(args.save)
    league, user_team = load_league(path)
    team = args.team or user_team
    t = league.teams[team]
    acts = [(args.release, R.release), (args.promote, R.promote), (args.demote, R.demote), (args.elevate, R.elevate)]
    if any(k for k, _ in acts) or args.auto or args.inactive or args.activate_gameday:
        if team != user_team:
            sys.exit("다른 팀 로스터는 바꿀 수 없습니다.")
        moves = []
        for key, fn in acts:
            if not key:
                continue
            p = _find(league, team, key)
            if fn is R.elevate:
                ok, why = R.can_elevate(league, team, p)
                if not ok:
                    sys.exit(why)
            if fn is R.promote and len(R.active(league, team)) >= R.limits()["active_max"]:
                sys.exit("53인 가득 — 먼저 방출하세요")
            moves.append(fn(league, team, p))
        if args.inactive:
            t.inactives.append(_find(league, team, args.inactive).id)
        if args.activate_gameday:
            pid = _find(league, team, args.activate_gameday).id
            t.inactives = [i for i in t.inactives if i != pid]
        if args.auto:
            t.auto_roster = args.auto == "on"
        for m in moves:
            print(m.text())
        record_transactions(path, league.season, league.week, moves)
        save_team_state(path, league)
    act = R.active(league, team)
    game = {p.id for p in R.gameday_actives(league, team)}
    lim = R.limits()
    print(f"\n{t.name} 로스터 — 53인 {len(act)}/{lim['active_max']}, 연습 스쿼드 {len(R.practice_squad(league, team))}/"
          f"{lim['practice_squad']}, 경기 당일 활성 {len(game)}/{lim['gameday_active']}, "
          f"자동 관리 {'켜짐' if t.auto_roster else '꺼짐'}")
    for g in R.GROUPS:
        ps = sorted((p for p in act if R.GROUP_OF.get(p.position) == g), key=position_rating, reverse=True)
        cells = []
        for p in ps:
            mark = "" if p.id in game else ("✚" if p.injured else "·")
            cells.append(f"{p.name.split()[-1]}{mark} {position_rating(p):.1f}")
        print(f"  {g:<4} " + ", ".join(cells))
    ps = sorted(R.practice_squad(league, team), key=position_rating, reverse=True)
    print("  연습 스쿼드: " + ", ".join(f"{p.name.split()[-1]}({p.position.value} {position_rating(p):.1f}"
                                       f"{', 승격 ' + str(p.elevations) if p.elevations else ''})" for p in ps))
    ir = [p for p in league.roster(team, (R.RosterStatus.IR,))]
    print(f"  IR {len(ir)}명: " + ", ".join(f"{p.name.split()[-1]}({p.position.value})" for p in ir))
    print("  (✚ 부상 결장, · 경기 당일 비활성)")


def cmd_fa(args) -> None:
    from .db.store import load_league, record_transactions, save_team_state
    from .ratings.position_rating import position_rating
    from .season import roster as R
    path = Path(args.save)
    league, user_team = load_league(path)
    if args.sign:
        cands = [p for p in league.free_agents() if p.id == args.sign or args.sign.lower() in p.name.lower()]
        if len(cands) != 1:
            sys.exit(f"FA '{args.sign}'를 하나로 특정할 수 없습니다 ({len(cands)}명)")
        ok, why = R.can_sign(league, user_team, cands[0], args.ps)
        if not ok:
            sys.exit(why)
        m = R.sign(league, user_team, cands[0], args.ps)
        record_transactions(path, league.season, league.week, [m])
        save_team_state(path, league)
        print(m.text())
        return
    group = args.pos.upper() if args.pos else None
    if group and group not in R.GROUPS:
        sys.exit(f"포지션 그룹: {', '.join(R.GROUPS)}")
    fa = R.free_agents(league, group)[: args.top]
    print(f"FA 풀 {'(' + group + ')' if group else ''} — 상위 {len(fa)}명")
    for p in fa:
        age = p.age_on(league.season_start())
        print(f"  {p.id:<14} {p.position.value:<4} {p.name:<24} PR {position_rating(p):>4.1f}  {age:>4.1f}세  "
              f"경력 {p.years_exp}년")


def cmd_owner(args) -> None:
    from .db.store import load_league, save_owner
    from .season import owner as O
    from .season.runner import ensure_owner
    path = Path(args.save)
    league, user_team = load_league(path)
    for line in ensure_owner(path, league, user_team):
        print(line)
    st = league.owner
    if st is None:
        sys.exit("사용자 팀이 없습니다.")
    if args.firing:
        st.firing = args.firing == "on"
        if not st.firing and st.fired:
            st.fired = False
            print("샌드박스 모드: 해고 없이 계속합니다.")
        save_owner(path, league)
    pr = st.projection
    print(f"\n{league.teams[st.team].name} 구단주 — {O.TIERS[st.tier]}")
    print(f"  예상 {st.wins_mean:.1f}승 (±{st.wins_sd:.1f}), 플레이오프 {pr.get('p_playoffs', 0) * 100:.0f}%, "
          f"컨퍼런스 결승 {pr.get('p_conf_final', 0) * 100:.0f}%, 우승 {pr.get('p_title', 0) * 100:.0f}%")
    res = O.goal_results(st, league, path) if any(g.played for g in league.schedule) else {}
    mark = lambda g: "" if g not in res else (" ✓" if res[g] else " ✗")  # noqa: E731
    print(f"  주 목표: {O.goal_label(st.main_goal)}{mark(st.main_goal)}")
    for g in st.sub_goals:
        print(f"  보조 목표: {O.SUB_GOALS[g]}{mark(g)}")
    bar = "█" * int(st.confidence / 5)
    print(f"  신뢰도 {st.confidence:.0f}/100 {bar}  경고 {st.warnings}/2  해고 {'켜짐' if st.firing else '꺼짐'}"
          + (f"  시즌 평가 {st.grade}" if st.grade else "") + ("  [해고됨]" if st.fired else ""))
    print("  최근 변화: " + " · ".join(f"{w}주 {v:.0f} ({r})" for w, v, r in st.history[-5:]))
    print("\n인박스")
    for m in st.inbox[-args.inbox:]:
        print(f"  [{m['week']}주] {m['text']}")


def add_parsers(sub) -> None:
    p = sub.add_parser("owner", help="구단주 목표·신뢰도·인박스 (F12)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--firing", choices=["on", "off"], help="해고 켜기/끄기 (끄면 샌드박스)")
    p.add_argument("--inbox", type=int, default=8)
    p.set_defaults(func=cmd_owner)

    p = sub.add_parser("roster", help="로스터·연습 스쿼드·경기 당일 명단 (F3)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--team")
    p.add_argument("--auto", choices=["on", "off"], help="대체 영입·임시 승격 자동 관리")
    p.add_argument("--release")
    p.add_argument("--promote", help="연습 스쿼드 → 53인")
    p.add_argument("--demote", help="53인 → 연습 스쿼드")
    p.add_argument("--elevate", help="이번 경기 연습 스쿼드 임시 승격")
    p.add_argument("--inactive", help="경기 당일 비활성 지정")
    p.add_argument("--activate-gameday", help="비활성 지정 취소")
    p.set_defaults(func=cmd_roster)

    p = sub.add_parser("fa", help="FA 풀·대체 영입 (F3-8)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--pos", help="포지션 그룹 (QB, RB, WR, TE, OL, EDGE, DT, LB, CB, S, K, P, LS)")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--sign")
    p.add_argument("--ps", action="store_true", help="연습 스쿼드로 영입")
    p.set_defaults(func=cmd_fa)

    p = sub.add_parser("injuries", help="부상 리포트·출전 결정·IR 관리 (F10)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--team")
    p.add_argument("--sit", help="Questionable 선수 이번 주 휴식 (id 또는 이름)")
    p.add_argument("--play", help="휴식 결정 취소")
    p.add_argument("--ir", help="IR 등재")
    p.add_argument("--activate", help="IR 복귀 지정")
    p.set_defaults(func=cmd_injuries)
