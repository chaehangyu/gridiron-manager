"""S1 새 게임/불러오기, S2 홈(인박스), 진행(경기·주·시즌), 작업 진행 표시."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ... import config
from ...db import store
from ...season import injuries as INJ
from ...season import roster as R
from ...season import runner
from .. import jobs, state, views
from ..app import need_ctx, render

router = APIRouter()


def _teams_by_division(league) -> list[tuple[str, list]]:
    out = []
    for conf in ("AFC", "NFC"):
        for div in ("East", "North", "South", "West"):
            ts = sorted((t for t in league.teams.values() if t.conference == conf and t.division == div),
                        key=lambda t: t.name)
            out.append((f"{conf} {div}", ts))
    return out


@router.get("/")
def root(request: Request):
    return RedirectResponse("/home" if state.current(request) else "/new", status_code=303)


@router.get("/new", response_class=HTMLResponse)
def new_game(request: Request):
    from ...data.real_league import load_real_league
    league = load_real_league(2026)
    return render(request, "new_game.html", state.current(request), slots=state.slots(),
                  divisions=_teams_by_division(league))


@router.post("/new")
def create_game(request: Request, team: str = Form(...), slot: str = Form(...), source: str = Form("real")):
    try:
        path = state.slot_path(slot)
    except ValueError as e:
        return HTMLResponse(f"<p>{e}</p>", status_code=400)
    from ...cli import _load_source

    def work(job: jobs.Job):
        job.log("리그 불러오는 중…", 0.05)
        league = _load_source(source, 2026)
        store.save_league(league, path, user_team=team)
        job.log("구단주 기대치 계산 중 — 엔진으로 정규시즌 2회 + 200시즌 투영 (약 1분)", 0.2)
        lg, user = store.load_league(path)
        for line in runner.ensure_owner(path, lg, user):
            job.log(line)
        store.add_news(path, lg.season, 0, [("owner", m["text"]) for m in (lg.owner.inbox if lg.owner else [])])
        return "/home"

    job = jobs.start(f"새 게임 — {team}", work)
    resp = RedirectResponse(f"/jobs/{job.id}", status_code=303)
    resp.set_cookie("slot", slot, max_age=10 * 365 * 86400)
    return resp


@router.post("/load/{name}")
def load_slot(name: str):
    state.slot_path(name)
    resp = RedirectResponse("/home", status_code=303)
    resp.set_cookie("slot", name, max_age=10 * 365 * 86400)
    return resp


@router.post("/delete/{name}")
def delete_slot(request: Request, name: str):
    p = state.slot_path(name)
    if p.exists():
        state.invalidate(p)
        p.unlink()
    resp = RedirectResponse("/new", status_code=303)
    if request.cookies.get("slot") == name:
        resp.delete_cookie("slot")
    return resp


def training_label(tp) -> str:
    from ...tactics.training import FOCUS_LABELS
    lab = lambda f: "-" if not f else FOCUS_LABELS.get(f.split(":")[0], f) + (  # noqa: E731
        f"({f.split(':')[1]})" if ":" in f and not f.endswith("auto") else "")
    return f"{lab(tp.main)} + {lab(tp.sub)} · 강도 {dict(light='가볍게', normal='보통', hard='강하게')[tp.intensity]}"


def todo(ctx) -> list[dict]:
    """이번 주 할 일 (S2)."""
    lg, me = ctx.league, ctx.user
    out = []
    if lg.phase == "offseason":
        return [{"text": "시즌이 끝났습니다. 구단주 평가를 확인하세요.", "href": "/owner"}]
    q = [p for p in lg.roster(me) if p.injury and p.injury.weeks_remaining == 0 and not p.injury.sit]
    if q:
        out.append({"text": f"출전 의문(Questionable) {len(q)}명 — 출전 여부 결정", "href": "/injuries"})
    n = len(R.active(lg, me))
    if n < R.limits()["active_max"]:
        out.append({"text": f"53인 로스터 {R.limits()['active_max'] - n}자리 비어 있음 — FA 영입", "href": "/roster?tab=fa"})
    nxt = views.next_game(lg, me)
    t = lg.teams[me]
    if nxt and t.gameplan_week != nxt.week:
        out.append({"text": f"{nxt.week}주차 게임플랜 미설정 (상대 스카우팅 리포트 확인)", "href": "/gameplan"})
    out.append({"text": f"주간 훈련: {training_label(t.training)}", "href": "/training"})
    return out


@router.get("/home", response_class=HTMLResponse)
def home(request: Request):
    ctx = need_ctx(request)
    lg, me = ctx.league, ctx.user
    nxt = views.next_game(lg, me)
    nxt_row = views.game_row(lg, nxt) if nxt else None
    if nxt:
        p = views.win_prob(lg, nxt.home, nxt.away, nxt.neutral_site)
        nxt_row["my_wp"] = None if p is None else (p if nxt.home == me else 1 - p)
        nxt_row["opp"] = nxt.away if nxt.home == me else nxt.home
        nxt_row["opp_rec"] = views.record(lg, nxt_row["opp"])
        nxt_row["this_week"] = nxt.week == lg.week
    remaining = [g for g in lg.games_in_week(lg.week) if not g.played]
    recent = [views.game_row(lg, g, me) for g in sorted(lg.schedule, key=lambda g: g.week)
              if g.played and me in (g.home, g.away)][-5:]
    inj = INJ.report_rows(lg, me)
    return render(request, "home.html", ctx, next=nxt_row, remaining=len(remaining), recent=recent,
                  todo=todo(ctx), news=store.news(ctx.path, lg.season, 25), division=views.division_table(lg, me),
                  injuries=[r for r in inj if not r["ir"]][:8], ir_count=sum(r["ir"] for r in inj),
                  owner=lg.owner, season_over=runner.season_over(lg))


# ── 진행 ────────────────────────────────────────────────────
@router.post("/play/{what}")
def play(request: Request, what: str, pbp: int = Form(0)):
    ctx = need_ctx(request)
    path, name = ctx.path, ctx.name

    def week_job(job: jobs.Job, until: str | None):
        league, user = store.load_league(path)
        n_weeks = 0
        while not runner.season_over(league):
            if until is None and n_weeks == 1:
                break
            if until == "regular" and league.phase == "playoffs":
                break
            title = views.week_title(league)
            job.log(title, None)

            def on_game(g, out, title=title):
                mark = " ◀" if user in (g.home, g.away) else ""
                job.log(f"  {g.away} {out.away_score} @ {g.home} {out.home_score}{mark}")
            for n in runner.sim_week(path, league, user, on_game):
                job.log("• " + n)
            n_weeks += 1
            if until:
                job.progress = min(0.99, league.week / 23)
        return "/home"

    if what == "game":
        def game_job(job: jobs.Job):
            league, user = store.load_league(path)
            g = next((g for g in league.games_in_week(league.week) if user in (g.home, g.away) and not g.played), None)
            if g is None:
                job.log("이번 주 우리 경기가 없습니다.")
                return "/home"
            job.log(f"{views.week_title(league)} {g.away} @ {g.home} 경기 진행…", 0.3)
            out = runner.play_game(path, league, g, user, pbp=True)
            job.log(f"{g.away} {out.away_score} @ {g.home} {out.home_score}", 0.9)
            for n in runner.finish_week(path, league, g.week, user):
                job.log("• " + n)
            return f"/match/{g.game_id}"
        job = jobs.start("우리 경기 진행", game_job)
    elif what == "week":
        job = jobs.start("이번 주 진행", lambda j: week_job(j, None))
    elif what in ("regular", "end"):
        job = jobs.start("정규시즌 끝까지" if what == "regular" else "시즌 끝까지", lambda j: week_job(j, what))
    else:
        return HTMLResponse("알 수 없는 진행", status_code=404)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/jobs/{jid}", response_class=HTMLResponse)
def job_page(request: Request, jid: int):
    job = jobs.JOBS.get(jid)
    if job is None:
        return RedirectResponse("/home", status_code=303)
    if request.headers.get("HX-Request"):
        resp = render(request, "partials/job.html", None, j=job)
        if job.done and not job.error:
            resp.headers["HX-Redirect"] = job.redirect
        return resp
    return render(request, "job.html", state.current(request), j=job)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    ctx = need_ctx(request)
    return render(request, "settings.html", ctx, rules=config.load("league_rules"))


@router.post("/settings")
def settings_save(request: Request, firing: str = Form("on"), auto_roster: str = Form("on"),
                  injury_risk: str = Form("standard")):
    ctx = need_ctx(request)
    lg = ctx.league
    t = ctx.team
    t.auto_roster = auto_roster == "on"
    t.tactics.management.injury_risk = injury_risk
    if lg.owner is not None:
        lg.owner.firing = firing == "on"
        if not lg.owner.firing:
            lg.owner.fired = False
        store.save_owner(ctx.path, lg)
    store.save_team_state(ctx.path, lg)
    state.invalidate(ctx.path)
    return RedirectResponse("/settings?saved=1", status_code=303)
