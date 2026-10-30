"""선수단 화면: S3 로스터·FA, S4 선수 프로필, S5 뎁스차트, S13 부상 관리."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ...db import store
from ...domain.depth import auto_depth_chart, validate_depth
from ...domain.models import RosterStatus
from ...domain.positions import OFFENSE_SLOTS, SPECIAL_SLOTS, SLOT_POSITIONS, defense_slots
from ...ratings.position_rating import position_rating
from ...ratings.roles import best_role
from ...season import injuries as INJ
from ...season import knowledge as KN
from ...season import roster as R
from .. import state, views
from ..app import need_ctx, render

router = APIRouter()
TABS = {"active": "53인", "ps": "연습 스쿼드", "ir": "IR", "fa": "FA 풀"}


def _row(lg, p, observer, gameday: set[str]) -> dict:
    lo, hi = KN.pr_range(lg, p, observer)
    br = best_role(p)
    inj = p.injury
    return {"id": p.id, "name": p.name, "pos": p.position.value, "group": R.GROUP_OF.get(p.position, ""),
            "age": p.age_on(lg.season_start()), "exp": p.years_exp, "pr": (lo + hi) / 2, "pr_txt": KN.fmt_range(lo, hi),
            "stars": KN.star_text(lo, hi), "role": br[1] if br and p.team == observer else "",
            "cond": p.condition, "inj": inj.type if inj else "", "inj_status": INJ.STATUS_KO[inj.status] if inj else "",
            "gameday": p.id in gameday, "elev": p.elevations, "knowledge": KN.knowledge(lg, p, observer)}


@router.get("/roster", response_class=HTMLResponse)
def roster_page(request: Request, tab: str = "active", pos: str = "", sort: str = "pr", team: str = ""):
    ctx = need_ctx(request)
    lg, me = ctx.league, ctx.user
    abbr = team or me
    status = {"active": RosterStatus.ACTIVE, "ps": RosterStatus.PRACTICE_SQUAD, "ir": RosterStatus.IR}
    gameday = {p.id for p in R.gameday_actives(lg, abbr)}
    if tab == "fa":
        players = R.free_agents(lg)[:300]
    else:
        players = lg.roster(abbr, (status.get(tab, RosterStatus.ACTIVE),))
    rows = [_row(lg, p, me, gameday) for p in players]
    if pos:
        rows = [r for r in rows if r["group"] == pos]
    keyf = {"pr": lambda r: -r["pr"], "age": lambda r: r["age"], "cond": lambda r: r["cond"],
            "pos": lambda r: (views.POS_ORDER.index(r["pos"]) if r["pos"] in views.POS_ORDER else 99, -r["pr"]),
            "name": lambda r: r["name"]}.get(sort, lambda r: -r["pr"])
    rows.sort(key=keyf)
    lim = R.limits()
    counts = {"active": len(R.active(lg, abbr)), "ps": len(R.practice_squad(lg, abbr)),
              "ir": len(lg.roster(abbr, (RosterStatus.IR,))), "gameday": len(gameday)}
    return render(request, "roster.html", ctx, rows=rows, tab=tab, tabs=TABS, pos=pos, sort=sort, groups=list(R.GROUPS),
                  lim=lim, counts=counts, abbr=abbr, own=abbr == me, teams=sorted(lg.teams),
                  msg=request.query_params.get("msg"), err=request.query_params.get("err"))


@router.post("/roster/{action}/{pid}")
def roster_action(request: Request, action: str, pid: str, back: str = Form("/roster")):
    ctx = need_ctx(request)
    lg, me = ctx.league, ctx.user
    p = lg.players.get(pid)
    if p is None:
        return RedirectResponse(f"{back}&err=선수 없음", status_code=303)
    sep = "&" if "?" in back else "?"
    err = None
    if action in ("sign", "sign_ps"):
        ok, why = R.can_sign(lg, me, p, action == "sign_ps")
        err = None if ok else why
        move = R.sign(lg, me, p, action == "sign_ps") if ok else None
    elif p.team != me:
        err, move = "우리 팀 선수가 아닙니다", None
    elif action == "release":
        move = R.release(lg, me, p)
    elif action == "promote":
        if len(R.active(lg, me)) >= R.limits()["active_max"]:
            err, move = "53인 가득 — 먼저 방출하세요", None
        else:
            move = R.promote(lg, me, p)
    elif action == "demote":
        move = R.demote(lg, me, p)
    elif action == "elevate":
        ok, why = R.can_elevate(lg, me, p)
        err, move = (None, R.elevate(lg, me, p)) if ok else (why, None)
    elif action in ("inactive", "activate_gameday"):
        t = ctx.team
        t.inactives = [i for i in t.inactives if i != pid] + ([pid] if action == "inactive" else [])
        move = None
    else:
        err, move = "알 수 없는 동작", None
    if err:
        state.invalidate(ctx.path)
        return RedirectResponse(f"{back}{sep}err={err}", status_code=303)
    if move:
        store.record_transactions(ctx.path, lg.season, lg.week, [move])
        store.add_news(ctx.path, lg.season, lg.week, [("roster", move.text())])
    store.save_team_state(ctx.path, lg)
    state.invalidate(ctx.path)
    return RedirectResponse(f"{back}{sep}msg={move.text() if move else '저장했습니다'}", status_code=303)


@router.get("/player/{pid}", response_class=HTMLResponse)
def player_page(request: Request, pid: str):
    ctx = need_ctx(request)
    p = ctx.league.players.get(pid)
    if p is None:
        return HTMLResponse("선수를 찾을 수 없습니다", status_code=404)
    prof = views.player_profile(ctx.league, p, ctx.user, ctx.path)
    st = views.season_stats(ctx.path, pid, ctx.league.season)
    stats = [(lab, st[k]) for k, lab in views.STAT_LABELS if st.get(k)]
    return render(request, "player.html", ctx, prof=prof, stats=stats,
                  team=ctx.league.teams.get(p.team) if p.team else None)


# ── 뎁스차트 (S5) ──────────────────────────────────────────
UNITS = {"offense": "공격", "defense": "수비", "special": "스페셜팀"}


def _unit_slots(team, unit: str) -> list[str]:
    return {"offense": OFFENSE_SLOTS, "defense": defense_slots(team.front), "special": SPECIAL_SLOTS}[unit]


@router.get("/depth", response_class=HTMLResponse)
def depth_page(request: Request, unit: str = "offense"):
    ctx = need_ctx(request)
    lg, t = ctx.league, ctx.team
    act = {p.id: p for p in R.active(lg, ctx.user)}
    gameday = {p.id for p in R.gameday_actives(lg, ctx.user)}

    def card(pid, slot):
        p = lg.players.get(pid)
        if p is None:
            return None
        return {"id": pid, "name": p.name, "pos": p.position.value, "pr": position_rating(p),
                "slot_pr": max(position_rating(p, x) for x in SLOT_POSITIONS[slot]) if slot not in ("KR", "PR", "H")
                else p.attributes["returning"], "inj": p.injured, "fit": p.position in SLOT_POSITIONS[slot],
                "out": pid not in act, "inactive": pid not in gameday}
    slots = []
    for slot in _unit_slots(t, unit):
        ids = t.depth_chart.get(slot, [])
        elig = sorted((p for p in act.values() if p.position in SLOT_POSITIONS[slot] and p.id not in ids),
                      key=lambda p: -position_rating(p))
        slots.append({"slot": slot, "players": [c for c in (card(i, slot) for i in ids) if c],
                      "pool": [card(p.id, slot) for p in elig[:8]]})
    warns = validate_depth(t, lg.players)
    return render(request, "depth.html", ctx, unit=unit, units=UNITS, slots=slots, warns=warns,
                  msg=request.query_params.get("msg"))


@router.post("/depth")
async def depth_save(request: Request):
    ctx = need_ctx(request)
    data = await request.json()
    t = ctx.team
    valid = set(_unit_slots(t, "offense") + _unit_slots(t, "defense") + _unit_slots(t, "special"))
    for slot, ids in data.items():
        if slot in valid:
            t.depth_chart[slot] = [i for i in ids if i in ctx.league.players][:6]
    store.save_depth_chart(ctx.path, t)
    state.invalidate(ctx.path)
    return JSONResponse({"ok": True, "warnings": validate_depth(t, ctx.league.players)})


@router.post("/depth/auto")
def depth_auto(request: Request, unit: str = Form("offense")):
    ctx = need_ctx(request)
    t, lg = ctx.team, ctx.league
    chart = auto_depth_chart(t, lg.roster(ctx.user))
    for slot in _unit_slots(t, unit):
        t.depth_chart[slot] = chart.get(slot, [])
    store.save_depth_chart(ctx.path, t)
    state.invalidate(ctx.path)
    return RedirectResponse(f"/depth?unit={unit}&msg=자동 편성 완료 (PR·컨디션·부상 기준)", status_code=303)


# ── 부상 관리 (S13) ────────────────────────────────────────
@router.get("/injuries", response_class=HTMLResponse)
def injuries_page(request: Request, team: str = ""):
    ctx = need_ctx(request)
    lg = ctx.league
    abbr = team or ctx.user
    rows = INJ.report_rows(lg, abbr)
    for r in rows:
        p = lg.players[r["id"]]
        r["can_activate"] = INJ.can_activate(lg, p, lg.week) if r["ir"] else None
        r["questionable"] = p.injury.weeks_remaining == 0 and not r["ir"]
        r["concussion"] = p.injury.body_part == "concussion"
    league_rows = []
    if not team:
        for a in sorted(lg.teams):
            if a != ctx.user:
                rs = [r for r in INJ.report_rows(lg, a) if not r["ir"]]
                if rs:
                    league_rows.append((a, rs))
    return render(request, "injuries.html", ctx, rows=rows, abbr=abbr, own=abbr == ctx.user,
                  used=lg.ir_returns_used.get(ctx.user, 0), rules=INJ.rules(), league_rows=league_rows,
                  msg=request.query_params.get("msg"), err=request.query_params.get("err"))


@router.post("/injuries/{action}/{pid}")
def injury_action(request: Request, action: str, pid: str):
    ctx = need_ctx(request)
    lg = ctx.league
    p = lg.players.get(pid)
    if p is None or p.team != ctx.user:
        return RedirectResponse("/injuries?err=우리 팀 선수가 아닙니다", status_code=303)
    if action in ("sit", "play"):
        if p.injury is None or p.injury.weeks_remaining > 0:
            return RedirectResponse("/injuries?err=출전 여부는 Questionable 선수만 정할 수 있습니다", status_code=303)
        p.injury.sit = action == "sit"
        msg = f"{p.name}: 이번 주 {'휴식' if action == 'sit' else '출전'}"
    elif action == "ir":
        if p.roster_status != RosterStatus.ACTIVE or p.injury is None:
            return RedirectResponse("/injuries?err=부상 중인 53인 선수만 IR에 올릴 수 있습니다", status_code=303)
        INJ.place_ir(lg, p, max(0, lg.week - 1))
        msg = f"{p.name} IR 등재"
    elif action == "activate":
        ok, why = INJ.can_activate(lg, p, lg.week)
        if not ok:
            return RedirectResponse(f"/injuries?err=복귀 불가: {why}", status_code=303)
        if len(R.active(lg, ctx.user)) >= R.limits()["active_max"]:
            return RedirectResponse("/injuries?err=53인 가득 — 먼저 방출하세요", status_code=303)
        INJ.activate(lg, p, lg.week)
        msg = f"{p.name} IR 복귀"
    else:
        return RedirectResponse("/injuries", status_code=303)
    store.save_team_state(ctx.path, lg)
    store.add_news(ctx.path, lg.season, lg.week, [("injury", msg)])
    state.invalidate(ctx.path)
    return RedirectResponse(f"/injuries?msg={msg}", status_code=303)
