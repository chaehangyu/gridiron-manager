"""경기·리그 화면: S8 매치 센터, S9 경기 결과, S10 일정·순위·플레이오프, S11 리그 통계, S15 구단주."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ...season import game_report as GR
from ...season import owner as O
from ...season import standings as ST
from ...season.runner import ROUND_LABEL
from .. import match, views
from ..app import need_ctx, render

router = APIRouter()
TEAM_STATS = [("pts", "득점"), ("pssYds", "패싱 야드"), ("rusYds", "러싱 야드"), ("pss", "패스 시도"), ("pssCmp", "완성"),
              ("rus", "러싱 시도"), ("pssSk", "색 허용"), ("pssInt", "INT"), ("fmbLost", "펌블 잃음"), ("pen", "반칙"),
              ("penYds", "반칙 야드"), ("timePos", "공격 시간")]


def _game(ctx, game_id):
    return next((g for g in ctx.league.schedule if g.game_id == game_id), None)


@router.get("/match/{game_id}", response_class=HTMLResponse)
def match_page(request: Request, game_id: str, tab: str = "live"):
    ctx = need_ctx(request)
    lg = ctx.league
    g = _game(ctx, game_id)
    if g is None:
        return HTMLResponse("경기를 찾을 수 없습니다", status_code=404)
    teams, players = match.box(ctx.path, game_id)
    events = match.load_events(ctx.path, game_id) if g.played else []
    has_pbp = bool(events)
    tl = match.timeline(events, [g.home, g.away]) if has_pbp else None
    tac = GR.tactical_report(events, [g.home, g.away]) if has_pbp else None
    ratings = GR.player_ratings(lg, g, players, teams) if g.played else []
    rows = []
    for key, lab in TEAM_STATS:
        a, h = teams.get(g.away, {}).get(key, 0), teams.get(g.home, {}).get(key, 0)
        if key == "timePos":
            a, h = f"{int(a)}:{int(a % 1 * 60):02d}", f"{int(h)}:{int(h % 1 * 60):02d}"
        rows.append((lab, a, h))
    if tl:
        rows.append(("3rd down", f"{tl['third'][1][0]}/{tl['third'][1][1]}", f"{tl['third'][0][0]}/{tl['third'][0][1]}"))
    tot = ("총 야드", teams.get(g.away, {}).get("pssYds", 0) + teams.get(g.away, {}).get("rusYds", 0),
           teams.get(g.home, {}).get("pssYds", 0) + teams.get(g.home, {}).get("rusYds", 0))
    rows.insert(1, tot)
    qtrs = (teams.get(g.away, {}).get("ptsQtrs", []), teams.get(g.home, {}).get("ptsQtrs", []))
    ply = {"pass": [], "rush": [], "rec": [], "def": [], "kick": []}
    for pid, abbr, s in players:
        s = GR.derive(s)
        p = lg.players.get(pid)
        name = p.name if p else pid
        base = {"id": pid, "name": name, "team": abbr}
        if s.get("pss"):
            ply["pass"].append({**base, "c": s.get("pssCmp", 0), "a": s["pss"], "y": s.get("pssYds", 0),
                                "td": s.get("pssTD", 0), "int": s.get("pssInt", 0), "sk": s.get("pssSk", 0)})
        if s.get("rus"):
            ply["rush"].append({**base, "n": s["rus"], "y": s.get("rusYds", 0), "td": s.get("rusTD", 0),
                                "lng": s.get("rusLng", 0)})
        if s.get("rec") or s.get("tgt"):
            ply["rec"].append({**base, "n": s.get("rec", 0), "tgt": s.get("tgt", 0), "y": s.get("recYds", 0),
                               "td": s.get("recTD", 0)})
        if s.get("defTck") or s.get("defSk") or s.get("defInt"):
            ply["def"].append({**base, "tck": s.get("defTck", 0), "sk": s.get("defSk", 0), "int": s.get("defInt", 0),
                               "pd": s.get("defPssDef", 0)})
        if s.get("fga") or s.get("pnt"):
            ply["kick"].append({**base, "fg": f"{s.get('fg', 0)}/{s.get('fga', 0)}", "pnt": s.get("pnt", 0),
                                "py": s.get("pntYds", 0)})
    for k, key in (("pass", "y"), ("rush", "y"), ("rec", "y"), ("def", "tck")):
        ply[k].sort(key=lambda r: -r[key])
    return render(request, "match.html", ctx, g=views.game_row(lg, g, ctx.user), tab=tab, has_pbp=has_pbp, tl=tl,
                  rows=rows, qtrs=qtrs, ply=ply, home=lg.teams[g.home], away=lg.teams[g.away], tac=tac,
                  ratings=ratings, potg=ratings[0] if ratings else None)


@router.get("/match/{game_id}/timeline.json")
def match_timeline(request: Request, game_id: str):
    ctx = need_ctx(request)
    g = _game(ctx, game_id)
    tl = match.timeline(match.load_events(ctx.path, game_id), [g.home, g.away])
    return JSONResponse({"frames": tl["frames"], "wp": tl["wp"], "home": g.home, "away": g.away})


@router.get("/standings", response_class=HTMLResponse)
def standings_page(request: Request, view: str = "division", week: int | None = None):
    ctx = need_ctx(request)
    lg = ctx.league
    st = ST.compute(lg)
    started = any(g.played for g in lg.schedule)
    seed_of = {t: i + 1 for s in st.seeds.values() for i, t in enumerate(s)} if started else {}
    divs = []
    for (conf, div), teams in st.divisions.items():
        rows = []
        for t in teams:
            r = st.rec(t)
            rows.append({"abbr": t, "name": lg.teams[t].name, "rec": r.text(), "pct": r.pct, "pf": r.pf, "pa": r.pa,
                         "net": r.net, "div": st.table.rec(t, st.table.div_teams(t) - {t}).text(),
                         "conf": st.table.rec(t, st.table.conf_teams(t) - {t}).text(), "seed": seed_of.get(t),
                         "me": t == ctx.user, "color": lg.teams[t].color})
        divs.append((f"{conf} {div}", rows))
    conf_order = {c: [{"abbr": t, "name": lg.teams[t].name, "rec": st.rec(t).text(), "seed": seed_of.get(t),
                       "me": t == ctx.user} for t in order] for c, order in st.conference_order.items()}
    rounds = []
    for rnd in ("WC", "DIV", "CON", "SB"):
        gs = [views.game_row(lg, g, ctx.user) for g in lg.schedule if g.game_type == rnd]
        if gs:
            rounds.append((ROUND_LABEL[rnd], gs))
    weeks = sorted({g.week for g in lg.schedule})
    wk = week or min(lg.week, max(weeks))
    sched = [views.game_row(lg, g, ctx.user) for g in lg.schedule if g.week == wk]
    mine = [views.game_row(lg, g, ctx.user) for g in sorted(lg.schedule, key=lambda g: g.week) if ctx.user in (g.home, g.away)]
    return render(request, "standings.html", ctx, view=view, divs=divs, conf_order=conf_order, rounds=rounds,
                  weeks=weeks, wk=wk, sched=sched, mine=mine, champion=ST.champion(lg), started=started)


@router.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request):
    ctx = need_ctx(request)
    from sqlmodel import Session, select

    from ...db import schema as S
    from ...db.store import engine_for
    lg = ctx.league
    tot: dict[str, dict] = {}
    team_tot: dict[str, dict] = {}
    with Session(engine_for(ctx.path)) as s:
        reg = {g.id for g in s.exec(select(S.GameRow).where(S.GameRow.season == lg.season)
                                    .where(S.GameRow.game_type == "REG").where(S.GameRow.status == "final"))}
        for r in s.exec(select(S.PlayerGameStatsRow)):
            if r.game_id not in reg:
                continue
            d = tot.setdefault(r.player_id, {"team": r.team})
            d["team"] = r.team
            for k, v in GR.derive(r.stats).items():
                if isinstance(v, (int, float)):
                    d[k] = d.get(k, 0) + v
        for r in s.exec(select(S.TeamGameStatsRow)):
            if r.game_id not in reg:
                continue
            d = team_tot.setdefault(r.team, {"g": 0})
            d["g"] += 1
            for k in ("pts", "pssYds", "rusYds", "pssInt", "fmbLost", "pssSk"):
                d[k] = d.get(k, 0) + (r.stats.get(k, 0) or 0)
    opp_pts: dict[str, float] = {}
    for g in lg.schedule:
        if g.game_type == "REG" and g.played:
            opp_pts[g.home] = opp_pts.get(g.home, 0) + g.away_score
            opp_pts[g.away] = opp_pts.get(g.away, 0) + g.home_score

    def board(key, label, extra=None, n=10):
        rows = sorted(((pid, d) for pid, d in tot.items() if d.get(key)), key=lambda x: -x[1][key])[:n]
        return {"label": label, "rows": [{"id": pid, "name": lg.players[pid].name if pid in lg.players else pid,
                                          "pos": lg.players[pid].position.value if pid in lg.players else "",
                                          "team": d["team"], "v": d[key], "x": extra(d) if extra else "",
                                          "me": d["team"] == ctx.user} for pid, d in rows]}
    boards = [board("pssYds", "패싱 야드", lambda d: f"{d.get('pssCmp', 0):.0f}/{d.get('pss', 0):.0f}, TD {d.get('pssTD', 0):.0f}, INT {d.get('pssInt', 0):.0f}"),
              board("pssTD", "패싱 TD"), board("rusYds", "러싱 야드", lambda d: f"{d.get('rus', 0):.0f}회, TD {d.get('rusTD', 0):.0f}"),
              board("recYds", "리시빙 야드", lambda d: f"{d.get('rec', 0):.0f}리셉션, TD {d.get('recTD', 0):.0f}"),
              board("defSk", "색"), board("defInt", "인터셉션"), board("defTck", "태클"),
              board("fg", "필드골 성공", lambda d: f"{d.get('fg', 0):.0f}/{d.get('fga', 0):.0f}")]
    teams = []
    for a, d in team_tot.items():
        g = max(1, d["g"])
        teams.append({"abbr": a, "name": lg.teams[a].name, "ppg": d["pts"] / g, "papg": opp_pts.get(a, 0) / g,
                      "ypg": (d["pssYds"] + d["rusYds"]) / g, "pass": d["pssYds"] / g, "rush": d["rusYds"] / g,
                      "to": (d["pssInt"] + d["fmbLost"]) / g, "me": a == ctx.user})
    teams.sort(key=lambda r: -r["ppg"])
    return render(request, "stats.html", ctx, boards=boards, teams=teams)


@router.get("/awards", response_class=HTMLResponse)
def awards_page(request: Request):
    ctx = need_ctx(request)
    from ...season import awards as AW
    return render(request, "awards.html", ctx, res=AW.compute(ctx.league, ctx.path), labels=AW.AWARDS,
                  min_games=AW.MIN_GAMES)


@router.get("/owner", response_class=HTMLResponse)
def owner_page(request: Request):
    ctx = need_ctx(request)
    lg = ctx.league
    st = lg.owner
    if st is None:
        return render(request, "owner.html", ctx, st=None)
    played = any(g.played for g in lg.schedule)
    res = O.goal_results(st, lg, ctx.path) if played else {}
    goals = [{"label": O.goal_label(st.main_goal), "main": True, "ok": res.get(st.main_goal)}] + \
            [{"label": O.SUB_GOALS[g], "main": False, "ok": res.get(g)} for g in st.sub_goals]
    return render(request, "owner.html", ctx, st=st, tier=O.TIERS[st.tier], goals=goals, final=lg.phase == "offseason",
                  hist=[{"w": w, "v": v, "r": r} for w, v, r in st.history])
