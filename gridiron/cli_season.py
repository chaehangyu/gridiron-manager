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


def _season_stats(path: Path, pid: str, season: int) -> dict:
    from sqlmodel import Session, select

    from .db import schema as S
    from .db.store import engine_for
    tot: dict = {}
    with Session(engine_for(path)) as s:
        q = select(S.PlayerGameStatsRow, S.GameRow).where(S.PlayerGameStatsRow.player_id == pid) \
            .where(S.GameRow.id == S.PlayerGameStatsRow.game_id).where(S.GameRow.season == season)
        for r, _ in s.exec(q):
            for k, v in r.stats.items():
                if isinstance(v, (int, float)):
                    tot[k] = tot.get(k, 0) + v
    return tot


def _injury_history(path: Path, pid: str) -> list:
    from sqlmodel import Session, select

    from .db import schema as S
    from .db.store import engine_for
    with Session(engine_for(path)) as s:
        return list(s.exec(select(S.InjuryRow).where(S.InjuryRow.player_id == pid).order_by(S.InjuryRow.id)))


def cmd_player(args) -> None:
    """선수 프로필 (S4): 능력치(다른 팀 선수는 파악도 범위), 포지션별 PR, 역할 평가, 숨김 능력치 코멘트, 부상 이력, 기록."""
    from .db.store import load_league
    from .domain.attributes import ATTRIBUTES, HIDDEN_KEYS, grade_label
    from .domain.positions import Position
    from .ratings.position_rating import position_rating
    from .ratings.roles import role_ratings
    from .season import knowledge as KN
    path = Path(args.save)
    league, user_team = load_league(path)
    cands = [p for p in league.players.values() if p.id == args.name or args.name.lower() in p.name.lower()]
    if not cands:
        sys.exit(f"선수 '{args.name}'를 찾을 수 없습니다")
    if len(cands) > 1 and not any(p.id == args.name for p in cands):
        for p in cands[:15]:
            print(f"  {p.id:<14} {p.position.value:<4} {p.name} ({p.team or 'FA'})")
        sys.exit("여러 명입니다. id로 지정하세요.")
    p = next((c for c in cands if c.id == args.name), cands[0])
    own = p.team == user_team
    k = KN.knowledge(league, p, user_team)
    lo, hi = KN.pr_range(league, p, user_team)
    age = p.age_on(league.season_start())
    pr_txt = KN.fmt_range(lo, hi)
    print(f"\n{p.name} — {p.position.value}, {p.team or 'FA'} ({p.roster_status.value}), {age:.1f}세, "
          f"{p.height_in or '?'}in {p.weight_lb or '?'}lb, 경력 {p.years_exp}년")
    print(f"  PR {pr_txt} {KN.star_text(lo, hi)}   파악도 {k:.0f}/100   컨디션 {p.condition:.0f}")
    groups: dict[str, list[str]] = {}
    for d in ATTRIBUTES.values():
        if d.key in HIDDEN_KEYS:
            continue
        r = KN.attr_range(league, p, d.key, user_team)
        val = f"{p.attributes[d.key]:.0f}" if r and r[0] == r[1] else f"{r[0]:.0f}–{r[1]:.0f}"
        groups.setdefault(d.group, []).append(f"{d.label_ko} {val}")
    for g, cells in groups.items():
        print(f"  [{g}] " + ", ".join(cells))
    if own:
        print("  숨김: " + ", ".join(KN.hidden_comments(p, league.week - 1 if league.week > 1 else 0)))
    else:
        print("  숨김: 비공개")
    special = (Position.K, Position.P, Position.LS)
    top = sorted(((pos, position_rating(p, pos)) for pos in Position if pos == p.position or pos not in special),
                 key=lambda x: -x[1])[:3]
    print("  포지션별 PR: " + ", ".join(f"{pos.value} {KN.fmt_range(*KN.pr_range(league, p, user_team, pos))}"
                                     for pos, _ in top))
    rr = role_ratings(p)
    if rr:
        best = max(rr, key=lambda key: rr[key][1])
        cells = [f"{n} {KN.fmt_range(*KN.value_range(league, p, user_team, v, 'role:' + key))}"
                 + (" ◀" if key == best and own else "") for key, (n, v) in rr.items()]
        print("  역할: " + ", ".join(cells) + (f"  → {grade_label(rr[best][1])}" if own else ""))
    hist = _injury_history(path, p.id)
    if hist or p.injury:
        print("  부상 이력: " + "; ".join(f"{h.season} {h.week}주 {h.type} ({h.missed}경기 결장)" for h in hist))
    st = _season_stats(path, p.id, league.season)
    if st:
        keys = [("gp", "경기"), ("snaps", "스냅"), ("pssCmp", "완성"), ("pss", "시도"), ("pssYds", "패싱야드"),
                ("pssTD", "패싱TD"), ("pssInt", "INT"), ("rus", "러싱"), ("rusYds", "러싱야드"), ("rec", "리셉션"),
                ("recYds", "리시빙야드"), ("defTck", "태클"), ("defSk", "색"), ("defInt", "INT"), ("defPssDef", "패스방어")]
        print("  시즌 기록: " + ", ".join(f"{lab} {st[k]:.0f}" for k, lab in keys if st.get(k)))


def cmd_scout(args) -> None:
    """스카우트 배정 (F13-3)과 파악도 현황."""
    from .db.store import load_league, save_team_state
    from .season import knowledge as KN
    from .season.roster import GROUPS
    path = Path(args.save)
    league, user_team = load_league(path)
    if args.assign:
        for tgt in args.assign:
            if tgt not in KN.TARGETS and not (tgt.startswith("pos:") and tgt[4:] in GROUPS):
                sys.exit(f"배정 대상: next_opponent, free_agents, pos:<{'|'.join(GROUPS)}>")
        if len(args.assign) != KN.SCOUTS:
            sys.exit(f"스카우트는 {KN.SCOUTS}명입니다")
        league.scout_assignments = list(args.assign)
        save_team_state(path, league)
    asg = league.scout_assignments or KN.DEFAULT_ASSIGN
    nxt = KN.next_opponent(league, user_team, league.week)
    print(f"스카우트 배정: " + ", ".join(asg) + (f"   (다음 상대 {nxt})" if nxt else ""))
    if nxt:
        ks = [KN.knowledge(league, p, user_team) for p in league.roster(nxt)]
        print(f"  {nxt} 선수 평균 파악도 {sum(ks) / max(1, len(ks)):.0f}")
    fa = league.free_agents()
    ks = [KN.knowledge(league, p, user_team) for p in fa]
    print(f"  FA 평균 파악도 {sum(ks) / max(1, len(ks)):.0f} ({len(fa)}명)")


def add_parsers(sub) -> None:
    p = sub.add_parser("player", help="선수 프로필 (능력치·PR·역할·부상 이력·기록)")
    p.add_argument("name")
    p.add_argument("--save", default="saves/career.sqlite")
    p.set_defaults(func=cmd_player)

    p = sub.add_parser("scout", help="스카우트 배정과 파악도 (F13)")
    p.add_argument("--save", default="saves/career.sqlite")
    p.add_argument("--assign", nargs="+", help="3명 배정 (예: next_opponent free_agents pos:WR)")
    p.set_defaults(func=cmd_scout)

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
