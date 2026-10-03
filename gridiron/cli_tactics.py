"""전술·게임플랜·주간 훈련 명령 (PRD F4·F11, M4). 웹 UI(M6) 전까지의 텍스트 화면.

    gridiron tactics --save S                                   # 현재 전술·숙련도·궁합
    gridiron tactics --save S --preset west_coast+tampa2
    gridiron tactics --save S --set offense.run_share=0.45 defense.blitz=1.4 predictability.lam=0.5
    gridiron tactics --save S --situ "3l|opp" pass=0.15 blitz=1.5 # 상황별 성향 (F4-3)
    gridiron tactics --save S --set offense.run_style=gap --preview  # 저장하지 않고 궁합 변화만 보기
    gridiron gameplan --save S                                  # 다음 상대 스카우팅 리포트 + 이번 주 조정
    gridiron gameplan --save S --set defense.blitz=1.8
    gridiron train --save S --main familiarity:cov_zone --sub opponent --intensity hard
"""
from __future__ import annotations

import sys
from pathlib import Path

from .tactics import familiarity as F
from .tactics.model import DEFENSE_PRESETS, OFFENSE_PRESETS, Tactics, preset


def _parse_value(v: str):
    if v.lower() in ("none", "null"):
        return None
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return float(v)
    except ValueError:
        return v


def apply_sets(data: dict, sets: list[str]) -> dict:
    """'offense.run_share=0.45', 'defense.coverage.C2=2.0' 같은 경로 지정 값을 dict에 쓴다."""
    for item in sets:
        if "=" not in item:
            sys.exit(f"설정은 key=value 형식입니다: {item}")
        path, v = item.split("=", 1)
        keys = path.split(".")
        cur = data
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = _parse_value(v)
    return data


def _bar(v: float, width: int = 20) -> str:
    n = int(round(v / 100 * width))
    return "█" * n + "·" * (width - n)


def print_tactics(league, abbr: str, t: Tactics, label: str = "현재 전술") -> None:
    from .tactics.fit import team_fit
    team = league.teams[abbr]
    o, d, pr = t.offense, t.defense, t.predictability
    run = f"{o.run_share:.0%}" if o.run_share is not None else "리그 평균"
    print(f"\n[{team.name}] {label} — {t.name}")
    print(f"  공격: 런 비율 {run}, 러닝 스타일 {o.run_style}, 깊이 배율 숏 {o.short:g}/미들 {o.mid:g}/딥 {o.deep:g}, "
          f"플레이액션 ×{o.play_action:g}, 스크린 ×{o.screen:g}, QB 성향 {o.qb_style:+g}")
    if o.personnel:
        print("        퍼스넬 배율 " + ", ".join(f"{k}:{v:g}" for k, v in sorted(o.personnel.items())))
    cov = ", ".join(f"{k}×{v:g}" for k, v in sorted(d.coverage.items())) or "리그 평균"
    print(f"  수비: 프론트 {team.front.value}, 커버리지 {cov}, 맨/존 {d.man_zone:+g}, 블리츠 ×{d.blitz:g}, 박스 {d.box:+g}")
    print(f"  예측 가능성: 상대 대응 강도 {pr.lam:g}, 성향 깨기 {pr.tendency_break}, 퍼스넬 섞기 {'켬' if pr.personnel_mix else '끔'}")
    if t.situational:
        print("  상황별: " + "; ".join(f"{k} {v}" for k, v in t.situational.items()))
    fit = team_fit(league, abbr, t)
    sh = fit["shares"]
    print(f"  대표 콜 비율: 존 런 {sh['zone_run']:.0%}, 맨 커버리지 {sh['man']:.0%}, "
          + ", ".join(f"{k} {v:.0%}" for k, v in sh["depth"].items()))
    print(f"  팀 궁합 {fit['team']:.3f}  (" + ", ".join(f"{g} {v:.3f}" for g, v in sorted(fit["groups"].items())) + ")")
    worst = fit["players"][:5]
    if worst:
        print("  궁합 낮은 주전: " + ", ".join(f"{r['name']}({r['pos']}, {r['style']}) {r['fit']:.2f}" for r in worst))
    for w in fit["warnings"]:
        print(f"  ⚠ {w['name']} ({w['pos']}) 궁합 {w['fit']:.2f} — 전술과 맞지 않음")


def print_familiarity(team) -> None:
    print("  전술 숙련도:")
    for d in F.DOMAINS:
        v = team.familiarity.get(d, F.BASE)
        print(f"    {F.LABELS[d]:<14} {_bar(v)} {v:5.1f}")


def _team_arg(args, user_team):
    team = args.team or user_team
    if not team:
        sys.exit("--team을 지정하세요 (세이브에 사용자 팀이 없습니다).")
    return team


def cmd_tactics(args) -> None:
    from .db.store import load_league, save_team_state
    path = Path(args.save)
    league, user_team = load_league(path)
    abbr = _team_arg(args, user_team)
    team = league.teams[abbr]
    t = team.tactics
    changed = False
    if args.preset:
        off, _, dfn = args.preset.partition("+")
        if off not in OFFENSE_PRESETS or (dfn and dfn not in DEFENSE_PRESETS):
            sys.exit(f"프리셋: 공격 {list(OFFENSE_PRESETS)} / 수비 {list(DEFENSE_PRESETS)} (예: west_coast+tampa2)")
        new = preset(off, dfn or "balanced")
        new.predictability, new.management, new.situational = t.predictability, t.management, t.situational
        t, changed = new, True
    if args.set:
        t, changed = Tactics.from_dict(apply_sets(t.to_dict(), args.set)), True
    if args.situ:
        key, *vals = args.situ
        data = t.to_dict()
        data["situational"][key] = {k: _parse_value(v) for k, v in (x.split("=", 1) for x in vals)}
        t, changed = Tactics.from_dict(data), True
    if args.clear_situ:
        t.situational, changed = {}, True
    errs = t.validate()
    if errs:
        sys.exit("전술 오류: " + "; ".join(errs))
    if changed and args.preview:
        print_tactics(league, abbr, team.tactics, "현재 전술")
        print_tactics(league, abbr, t, "변경 미리보기 (저장 안 함)")
        return
    if changed:
        if t.name == team.tactics.name and not args.preset:
            t.name = "custom"
        team.tactics = t
        save_team_state(path, league)
        print("전술을 저장했습니다.")
    print_tactics(league, abbr, team.tactics)
    print_familiarity(team)
    if not changed:
        print("\n프리셋: 공격 " + ", ".join(f"{k}({v[0]})" for k, v in OFFENSE_PRESETS.items()))
        print("        수비 " + ", ".join(f"{k}({v[0]})" for k, v in DEFENSE_PRESETS.items()))


def _next_game(league, abbr):
    return next((g for g in sorted(league.schedule, key=lambda g: (g.week, g.gameday or league.season_start()))
                 if abbr in (g.home, g.away) and not g.played and g.game_type == "REG"), None)


def cmd_gameplan(args) -> None:
    from .db.store import load_league, save_team_state
    from .tactics.scouting import report
    path = Path(args.save)
    league, user_team = load_league(path)
    abbr = _team_arg(args, user_team)
    team = league.teams[abbr]
    game = _next_game(league, abbr)
    if game is None:
        sys.exit("남은 경기가 없습니다.")
    opp_abbr = game.away if game.home == abbr else game.home
    opp = league.teams[opp_abbr]
    if args.clear:
        team.gameplan, team.gameplan_week = {}, None
        save_team_state(path, league)
        print("이번 주 게임플랜을 지웠습니다.")
    elif args.set:
        team.gameplan = apply_sets(dict(team.gameplan) if team.gameplan_week == game.week else {}, args.set)
        team.gameplan_week = game.week
        errs = team.tactics_for_week(game.week).validate()
        if errs:
            sys.exit("게임플랜 오류: " + "; ".join(errs))
        save_team_state(path, league)
        print("이번 주 게임플랜을 저장했습니다 (경기 후 기본 전술로 돌아갑니다).")
    r = report(opp.scouting or None, opp.last_tendency)
    print(f"\n{game.week}주차 상대: {opp.name} ({'원정' if game.home == abbr else '홈'}) — 스카우팅 리포트")
    if r["games"]:
        print(f"  이번 시즌 {r['games']}경기: 패스 비율 {r['pass_rate']:.0%}, 기대 대비 패스 {r['proe']:+.1%}")
    last = opp.last_tendency
    if last:
        lo, ld = last["offense"], last["defense"]
        print(f"  지난 시즌: 기대 대비 패스 {lo['proe']:+.1%}, 플레이액션 {lo['pa_rate']:.0%}, 스크린 {lo['screen_rate']:.0%}, "
              f"딥 {lo['deep_rate']:.0%}, 아웃사이드 런 {lo['outside_run']:.0%}")
        print(f"            블리츠 {ld['blitz_rate']:.0%}, 맨 커버리지 {ld['man_rate']:.0%}, "
              + ", ".join(f"{k} {v:.0%}" for k, v in sorted(ld["coverage"].items(), key=lambda kv: -kv[1])))
    if r["blitz_rate"] is not None:
        print(f"  예상 블리츠율 {r['blitz_rate']:.0%}, 커버리지 " +
              ", ".join(f"{k} {v:.0%}" for k, v in sorted(r["coverage"].items(), key=lambda kv: -kv[1])))
    if team.gameplan and team.gameplan_week == game.week:
        print(f"  이번 주 조정: {team.gameplan}")
        print_tactics(league, abbr, team.tactics_for_week(game.week), "이번 주 전술")


def cmd_train(args) -> None:
    from .db.store import load_league, save_team_state
    from .tactics.training import FOCUS_LABELS, INTENSITY, TrainingPlan
    path = Path(args.save)
    league, user_team = load_league(path)
    abbr = _team_arg(args, user_team)
    team = league.teams[abbr]
    if args.main or args.sub or args.intensity:
        plan = TrainingPlan(main=args.main or team.training.main,
                            sub=(None if args.sub == "none" else args.sub) if args.sub else team.training.sub,
                            intensity=args.intensity or team.training.intensity)
        errs = plan.validate()
        if errs:
            sys.exit("훈련 계획 오류: " + "; ".join(errs))
        team.training = plan
        save_team_state(path, league)
        print("훈련 계획을 저장했습니다 (다음 주 시작 때 적용).")
    tp = team.training
    print(f"\n[{team.name}] 주간 훈련 — 주 초점 {tp.main}, 보조 초점 {tp.sub}, 강도 {tp.intensity}")
    print("  초점: " + ", ".join(f"{k}({v})" for k, v in FOCUS_LABELS.items()) + "  · 숙련은 familiarity:<영역|auto>")
    print("  강도: " + ", ".join(f"{k}(효과 ×{m}, 컨디션 {c:+g})" for k, (m, c) in INTENSITY.items()))
    print_familiarity(team)
    roster = league.roster(abbr)
    if roster:
        avg = sum(p.condition for p in roster) / len(roster)
        print(f"  평균 컨디션 {avg:.1f}")


def print_game_tactics(out, league, abbr: str) -> None:
    """경기 결과 전술 리포트 (ENGINE_DESIGN §6.8, PRD F4-8e)."""
    rep = (out.tactics or {}).get(abbr)
    if not rep:
        return
    opp = out.game.away if out.game.home == abbr else out.game.home
    orep = out.tactics.get(opp, {})
    print(f"\n전술 리포트 — {league.teams[abbr].nickname}")
    print(f"  노출도 {rep['exposure']:.0f}/100 · 상대 적중률 {rep['countered_rate']:.0%} · "
          f"읽힘 손실 {rep['anticip_plays']}플레이 (평균 {rep['anticip_mean']:+.2f})")
    print(f"  궁합 손실 지수 {rep['fit_loss']:.1f} (우리 팀 콜이 선수에게 최적이 아니었던 정도) · 커버리지 붕괴 {rep['busts']}회")
    print(f"  상대 노출도 {orep.get('exposure', 0):.0f}/100 · 상대 대응 강도 {orep.get('lam', 0):.2f}")
