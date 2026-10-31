"""코칭 화면: S6 전술, S7 게임플랜, S14 주간 훈련, S16 스카우팅."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ...db import store
from ...tactics import familiarity as F
from ...tactics import preview as PV
from ...tactics.fit import team_fit
from ...tactics.model import (COVERS, DEFENSE_PRESETS, DOWN_DIST, FIELD, FOURTH_DOWN, OFFENSE_PRESETS, PERSONNEL,
                              PRESS, RUN_STYLES, TENDENCY_BREAK, TWO_POINT, Tactics, preset)
from ...tactics.training import FOCUS_LABELS, INTENSITY, TrainingPlan
from .. import state, views
from ..app import need_ctx, render

router = APIRouter()
RUN_STYLE_KO = {"mixed": "혼합", "inside_zone": "인사이드 존", "outside_zone": "아웃사이드 존", "gap": "갭/파워"}
DD_KO = {"1": "1st", "2s": "2nd 짧음", "2m": "2nd 중간", "2l": "2nd 김", "3s": "3rd 짧음", "3m": "3rd 중간",
         "3l": "3rd 김", "4": "4th"}
FIELD_KO = {"backed": "자기 진영 깊숙이", "own": "자기 진영", "opp": "상대 진영", "red": "레드존", "goal": "골라인"}


def _num(v: str):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def form_to_tactics(form, base: Tactics) -> Tactics:
    d = base.to_dict()
    d["offense"]["personnel"], d["defense"]["coverage"], d["situational"] = {}, {}, {}
    for k, v in form.items():
        if k.startswith("sit."):
            _, key, field = k.split(".", 2)
            x = _num(v)
            if isinstance(x, float) and ((field == "pass" and abs(x) > 1e-9) or (field == "blitz" and abs(x - 1) > 1e-9)):
                d["situational"].setdefault(key, {})[field] = x
            continue
        parts = k.split(".")
        if parts[0] not in ("offense", "defense", "predictability", "management"):
            continue
        cur = d
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = _num(v)
    if form.get("offense.run_share_avg"):
        d["offense"]["run_share"] = None
    d["offense"].pop("run_share_avg", None)
    d["predictability"]["personnel_mix"] = bool(form.get("predictability.personnel_mix"))
    d["offense"]["personnel"] = {k: v for k, v in d["offense"]["personnel"].items() if abs(v - 1) > 1e-9}
    d["defense"]["coverage"] = {k: v for k, v in d["defense"]["coverage"].items() if abs(v - 1) > 1e-9}
    t = Tactics.from_dict(d)
    t.name = form.get("name") or "custom"
    return t


def _fit_summary(league, abbr, t):
    fit = team_fit(league, abbr, t)
    return {"team": fit["team"], "groups": fit["groups"], "worst": fit["players"][:6], "warnings": fit["warnings"],
            "shares": fit["shares"]}


def _common(ctx):
    return dict(presets_off=OFFENSE_PRESETS, presets_def=DEFENSE_PRESETS, run_styles=RUN_STYLE_KO, press=PRESS,
                breaks=TENDENCY_BREAK, fourth=FOURTH_DOWN, twopt=TWO_POINT, covers=COVERS, personnel=PERSONNEL,
                dd=DOWN_DIST, field=FIELD, dd_ko=DD_KO, field_ko=FIELD_KO,
                fam=[(F.LABELS[d], ctx.team.familiarity.get(d, F.BASE)) for d in F.DOMAINS])


@router.get("/tactics", response_class=HTMLResponse)
def tactics_page(request: Request):
    ctx = need_ctx(request)
    t = ctx.team.tactics
    expo, ewarn = PV.exposure_estimate(t)
    return render(request, "tactics.html", ctx, t=t, fit=_fit_summary(ctx.league, ctx.user, t), expo=expo,
                  ewarn=ewarn, msg=request.query_params.get("msg"), err=request.query_params.get("err"), **_common(ctx))


@router.post("/tactics")
async def tactics_save(request: Request):
    ctx = need_ctx(request)
    form = await request.form()
    t = form_to_tactics(form, ctx.team.tactics)
    errs = t.validate()
    if errs:
        return RedirectResponse("/tactics?err=" + "; ".join(errs), status_code=303)
    ctx.team.tactics = t
    store.save_team_state(ctx.path, ctx.league)
    state.invalidate(ctx.path)
    return RedirectResponse("/tactics?msg=전술을 저장했습니다. 바뀐 영역은 숙련도가 낮으면 손해가 납니다 (훈련으로 회복).",
                            status_code=303)


@router.post("/tactics/preset")
async def tactics_preset(request: Request):
    ctx = need_ctx(request)
    form = await request.form()
    off, dfn = form.get("off", "balanced"), form.get("def", "balanced")
    old = ctx.team.tactics
    new = preset(off, dfn)
    new.predictability, new.management, new.situational = old.predictability, old.management, old.situational
    ctx.team.tactics = new
    store.save_team_state(ctx.path, ctx.league)
    state.invalidate(ctx.path)
    return RedirectResponse(f"/tactics?msg=프리셋 {off}+{dfn} 적용", status_code=303)


@router.post("/tactics/user-preset")
async def tactics_user_preset(request: Request):
    """사용자 프리셋 (F4-7c): 현재 전술 저장 / 불러오기 / 삭제."""
    ctx = need_ctx(request)
    form = await request.form()
    action, name = form.get("action"), (form.get("name") or "").strip()[:30]
    presets = ctx.league.user_presets
    if action == "save" and name:
        d = ctx.team.tactics.to_dict()
        d["name"] = name
        presets[name] = d
        msg = f"현재 전술을 '{name}' 프리셋으로 저장했습니다"
    elif action == "load" and name in presets:
        t = Tactics.from_dict(presets[name])
        ctx.team.tactics = t
        msg = f"내 프리셋 '{name}' 적용"
    elif action == "delete" and name in presets:
        presets.pop(name)
        msg = f"프리셋 '{name}' 삭제"
    else:
        return RedirectResponse("/tactics?err=프리셋 이름을 확인하세요", status_code=303)
    store.save_team_state(ctx.path, ctx.league)
    state.invalidate(ctx.path)
    return RedirectResponse(f"/tactics?msg={msg}", status_code=303)


@router.post("/tactics/preview", response_class=HTMLResponse)
async def tactics_preview(request: Request):
    """HTMX: 폼 값으로 궁합·노출도 미리보기 (저장 안 함)."""
    ctx = need_ctx(request)
    form = await request.form()
    t = form_to_tactics(form, ctx.team.tactics)
    errs = t.validate()
    expo, ewarn = PV.exposure_estimate(t)
    old_expo, _ = PV.exposure_estimate(ctx.team.tactics)
    return render(request, "partials/tactics_preview.html", ctx, errs=errs, fit=_fit_summary(ctx.league, ctx.user, t),
                  old_fit=_fit_summary(ctx.league, ctx.user, ctx.team.tactics), expo=expo, old_expo=old_expo,
                  ewarn=ewarn)


@router.post("/tactics/simulate", response_class=HTMLResponse)
async def tactics_simulate(request: Request):
    """HTMX: 다음 상대와 같은 시드로 현재 vs 새 전술 엔진 비교 (약 3–5초)."""
    ctx = need_ctx(request)
    form = await request.form()
    t = form_to_tactics(form, ctx.team.tactics)
    if t.validate():
        return HTMLResponse("<div class='err'>전술 값 오류</div>")
    g = views.next_game(ctx.league, ctx.user)
    opp = (g.away if g.home == ctx.user else g.home) if g else next(a for a in sorted(ctx.league.teams) if a != ctx.user)
    with state.LOCK:
        res = PV.simulate_compare(ctx.league, ctx.user, t, opp, n=int(form.get("n", 16)))
    return render(request, "partials/tactics_sim.html", ctx, r=res, opp=ctx.league.teams[opp].name)


# ── 게임플랜 (S7) ──────────────────────────────────────────
GP_FIELDS = [("offense.run_share", "런 비율", 0.2, 0.8, 0.01), ("offense.deep", "딥 패스 배율", 0.3, 2.5, 0.05),
             ("offense.play_action", "플레이액션 배율", 0.3, 2.5, 0.05), ("offense.screen", "스크린 배율", 0.3, 2.5, 0.05),
             ("defense.blitz", "블리츠 배율", 0.3, 3.0, 0.05), ("defense.man_zone", "맨(+)/존(−)", -1, 1, 0.05),
             ("defense.box", "박스 무게", -1, 1, 0.05), ("predictability.lam", "상대 대응 강도", 0, 0.7, 0.05)]


def _get(t: Tactics, path: str):
    sec, key = path.split(".")
    return getattr(getattr(t, sec), key)


@router.get("/gameplan", response_class=HTMLResponse)
def gameplan_page(request: Request):
    ctx = need_ctx(request)
    from ...cli_tactics import _next_game
    from ...season import injuries as INJ
    from ...tactics.scouting import report
    lg, me, team = ctx.league, ctx.user, ctx.team
    g = _next_game(lg, me) or views.next_game(lg, me)
    if g is None:
        return render(request, "gameplan.html", ctx, g=None)
    opp_abbr = g.away if g.home == me else g.home
    opp = lg.teams[opp_abbr]
    rep = report(opp.scouting or None, opp.last_tendency)
    week_t = team.tactics_for_week(g.week)
    fields = [{"path": p, "label": lab, "lo": lo, "hi": hi, "step": st, "base": _get(team.tactics, p),
               "val": _get(week_t, p), "set": p.split(".")[1] in (team.gameplan.get(p.split(".")[0], {})
                                                                 if team.gameplan_week == g.week else {})}
              for p, lab, lo, hi, st in GP_FIELDS]
    p = views.win_prob(lg, g.home, g.away, g.neutral_site)
    return render(request, "gameplan.html", ctx, g=views.game_row(lg, g), opp=opp, rep=rep, last=opp.last_tendency,
                  fields=fields, active=team.gameplan_week == g.week and bool(team.gameplan),
                  opp_inj=[r for r in INJ.report_rows(lg, opp_abbr) if not r["ir"]],
                  my_wp=None if p is None else (p if g.home == me else 1 - p), opp_rec=views.record(lg, opp_abbr),
                  covers=COVERS, msg=request.query_params.get("msg"), err=request.query_params.get("err"))


@router.post("/gameplan")
async def gameplan_save(request: Request):
    ctx = need_ctx(request)
    from ...cli_tactics import _next_game
    form = await request.form()
    team = ctx.team
    g = _next_game(ctx.league, ctx.user) or views.next_game(ctx.league, ctx.user)
    if g is None:
        return RedirectResponse("/gameplan", status_code=303)
    if form.get("clear"):
        team.gameplan, team.gameplan_week = {}, None
        msg = "이번 주 게임플랜을 지웠습니다"
    else:
        plan: dict = {}
        for p, *_ in GP_FIELDS:
            if form.get("use." + p):
                sec, key = p.split(".")
                plan.setdefault(sec, {})[key] = float(form.get(p))
        cov = {c: float(form.get("cov." + c)) for c in COVERS if form.get("cov." + c) not in (None, "", "1", "1.0")}
        if cov:
            plan.setdefault("defense", {})["coverage"] = {**team.tactics.defense.coverage, **cov}
        team.gameplan, team.gameplan_week = plan, g.week
        errs = team.tactics_for_week(g.week).validate()
        if errs:
            team.gameplan, team.gameplan_week = {}, None
            return RedirectResponse("/gameplan?err=" + "; ".join(errs), status_code=303)
        msg = "이번 주 게임플랜을 저장했습니다 (경기 후 기본 전술로 돌아갑니다)"
    store.save_team_state(ctx.path, ctx.league)
    state.invalidate(ctx.path)
    return RedirectResponse(f"/gameplan?msg={msg}", status_code=303)


# ── 주간 훈련 (S14) ────────────────────────────────────────
@router.get("/training", response_class=HTMLResponse)
def training_page(request: Request):
    ctx = need_ctx(request)
    from ...season.weekly import used_domains
    team = ctx.team
    roster = ctx.league.roster(ctx.user)
    avg = sum(p.condition for p in roster) / max(1, len(roster))
    low = sorted((p for p in roster if p.condition < 85), key=lambda p: p.condition)[:10]
    injured = [p for p in roster if p.injury is not None]
    return render(request, "training.html", ctx, tp=team.training, focuses=FOCUS_LABELS, intensity=INTENSITY,
                  domains=F.DOMAINS, dlabels=F.LABELS, fam=[(d, F.LABELS[d], team.familiarity.get(d, F.BASE))
                                                            for d in F.DOMAINS],
                  used=used_domains(team), avg=avg, low=low, injured=injured, msg=request.query_params.get("msg"),
                  err=request.query_params.get("err"))


@router.post("/training")
async def training_save(request: Request):
    ctx = need_ctx(request)
    form = await request.form()

    def focus(kind_key, dom_key):
        kind = form.get(kind_key) or None
        if kind in (None, "none"):
            return None
        return f"familiarity:{form.get(dom_key) or 'auto'}" if kind == "familiarity" else kind
    plan = TrainingPlan(main=focus("main", "main_dom") or "familiarity:auto", sub=focus("sub", "sub_dom"),
                        intensity=form.get("intensity", "normal"))
    errs = plan.validate()
    if errs:
        return RedirectResponse("/training?err=" + "; ".join(errs), status_code=303)
    ctx.team.training = plan
    store.save_team_state(ctx.path, ctx.league)
    state.invalidate(ctx.path)
    return RedirectResponse("/training?msg=훈련 계획을 저장했습니다 (다음 주 시작 때 적용)", status_code=303)


# ── 스카우팅 (S16) ─────────────────────────────────────────
@router.get("/scout", response_class=HTMLResponse)
def scout_page(request: Request):
    ctx = need_ctx(request)
    from ...season import knowledge as KN
    from ...season.roster import GROUPS
    lg, me = ctx.league, ctx.user
    asg = lg.scout_assignments or KN.DEFAULT_ASSIGN
    nxt = KN.next_opponent(lg, me, lg.week)
    teams = []
    for a in sorted(lg.teams):
        if a == me:
            continue
        ks = [KN.knowledge(lg, p, me) for p in lg.roster(a)]
        teams.append({"abbr": a, "name": lg.teams[a].name, "k": sum(ks) / max(1, len(ks)), "next": a == nxt})
    fa = lg.free_agents()
    fa_k = sum(KN.knowledge(lg, p, me) for p in fa) / max(1, len(fa))
    return render(request, "scout.html", ctx, asg=asg, nxt=nxt, teams=teams, fa_k=fa_k, groups=list(GROUPS),
                  n_scouts=KN.SCOUTS, msg=request.query_params.get("msg"))


@router.post("/scout")
async def scout_save(request: Request):
    ctx = need_ctx(request)
    from ...season import knowledge as KN
    form = await request.form()
    asg = [form.get(f"s{i}") or "next_opponent" for i in range(KN.SCOUTS)]
    ctx.league.scout_assignments = asg
    store.save_team_state(ctx.path, ctx.league)
    state.invalidate(ctx.path)
    return RedirectResponse("/scout?msg=스카우트 배정을 저장했습니다 (주 마감 때 파악도 반영)", status_code=303)
