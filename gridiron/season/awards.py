"""시즌 어워드와 올프로 (PRD F7-7).

정규시즌 경기별 선수 평점(game_report.player_rating)을 누적한 '평균 이상 기여'(Σ(평점 − 6.0))로 뽑는다.
MVP는 팀 성적(승수)도 반영하고, 신인상은 경력 0년 선수만. 시즌 중에는 '현재 레이스'로 같은 계산을 보여준다.
"""
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from ..db import schema as S
from ..db.store import engine_for
from ..domain.models import League
from . import standings as ST
from .game_report import derive, player_rating

OFFENSE = {"QB", "RB", "FB", "WR", "TE", "OT", "OG", "C"}
DEFENSE = {"EDGE", "DT", "LB", "CB", "S"}
ALL_PRO = [("QB", 1), ("RB", 1), ("WR", 3), ("TE", 1), ("OT", 2), ("OG", 2), ("C", 1), ("EDGE", 2), ("DT", 2),
           ("LB", 2), ("CB", 2), ("S", 2), ("K", 1), ("P", 1)]
AWARDS = [("mvp", "MVP"), ("opoy", "올해의 공격 선수"), ("dpoy", "올해의 수비 선수"), ("oroy", "올해의 공격 신인"),
          ("droy", "올해의 수비 신인")]
MIN_GAMES = 10


def season_values(league: League, path: Path) -> dict[str, dict]:
    """선수별 {games, value(Σ(평점−6)), avg, stats 합계, team}."""
    with Session(engine_for(path)) as s:
        games = {g.id: g for g in s.exec(select(S.GameRow).where(S.GameRow.season == league.season)
                                         .where(S.GameRow.game_type == "REG").where(S.GameRow.status == "final"))}
        teams = {(r.game_id, r.team): r.stats for r in s.exec(select(S.TeamGameStatsRow)) if r.game_id in games}
        rows = [r for r in s.exec(select(S.PlayerGameStatsRow)) if r.game_id in games]
    out: dict[str, dict] = {}
    for r in rows:
        p = league.players.get(r.player_id)
        if p is None:
            continue
        g = games[r.game_id]
        won = (g.home_score > g.away_score) if r.team == g.home else (g.away_score > g.home_score)
        rt = player_rating(p.position.value, r.stats, teams.get((r.game_id, r.team), {}), won)
        d = out.setdefault(r.player_id, {"games": 0, "value": 0.0, "sum": 0.0, "stats": {}, "team": r.team})
        d["team"] = r.team
        for k, v in derive(r.stats).items():
            if isinstance(v, (int, float)):
                d["stats"][k] = d["stats"].get(k, 0) + v
        if rt is not None:
            d["games"] += 1
            d["sum"] += rt
            d["value"] += rt - 6.0
    for d in out.values():
        d["avg"] = d["sum"] / d["games"] if d["games"] else 0.0
    return out


def _line(pos: str, st: dict) -> str:
    if pos == "QB":
        return f"{st.get('pssYds', 0):.0f}야드 TD {st.get('pssTD', 0):.0f} INT {st.get('pssInt', 0):.0f}"
    if pos in ("RB", "FB"):
        return f"러싱 {st.get('rusYds', 0):.0f}야드 TD {st.get('rusTD', 0):.0f} · 리시빙 {st.get('recYds', 0):.0f}야드"
    if pos in ("WR", "TE"):
        return f"{st.get('rec', 0):.0f}리셉션 {st.get('recYds', 0):.0f}야드 TD {st.get('recTD', 0):.0f}"
    if pos in DEFENSE:
        return f"태클 {st.get('defTck', 0):.0f} 색 {st.get('defSk', 0):.1f} INT {st.get('defInt', 0):.0f} PD {st.get('defPssDef', 0):.0f}"
    if pos == "K":
        return f"FG {st.get('fg', 0):.0f}/{st.get('fga', 0):.0f}"
    if pos == "P":
        return f"펀트 {st.get('pnt', 0):.0f}회 평균 {st.get('pntYds', 0) / max(1, st.get('pnt', 0)):.1f}야드"
    return f"{st.get('snaps', 0):.0f}스냅"


def compute(league: League, path: Path) -> dict:
    vals = season_values(league, path)
    tb = ST.Table.from_league(league)

    def entry(pid: str, score: float) -> dict:
        p, d = league.players[pid], vals[pid]
        return {"id": pid, "name": p.name, "pos": p.position.value, "team": d["team"], "games": d["games"],
                "avg": round(d["avg"], 2), "score": round(score, 1), "line": _line(p.position.value, d["stats"]),
                "rec": tb.rec(d["team"]).text()}

    def ranked(filt, bonus=lambda pid: 0.0, n=5, weight=lambda pid: 1.0):
        c = [(pid, d["value"] * weight(pid) + bonus(pid)) for pid, d in vals.items()
             if d["games"] >= MIN_GAMES and filt(league.players[pid])]
        c.sort(key=lambda x: -x[1])
        return [entry(pid, sc) for pid, sc in c[:n]]
    pos = lambda p: p.position.value  # noqa: E731
    team_bonus = lambda pid: 0.8 * tb.rec(vals[pid]["team"]).w  # noqa: E731  MVP: 팀 성적 반영
    # MVP 투표는 QB 중심 (실제 최근 MVP 대부분 QB): QB 기여 ×1.6
    qb_weight = lambda pid: 1.6 if league.players[pid].position.value == "QB" else 1.0  # noqa: E731
    out = {"mvp": ranked(lambda p: pos(p) in OFFENSE | DEFENSE, team_bonus, weight=qb_weight),
           "opoy": ranked(lambda p: pos(p) in OFFENSE - {"OT", "OG", "C"}),
           "dpoy": ranked(lambda p: pos(p) in DEFENSE),
           "oroy": ranked(lambda p: pos(p) in OFFENSE and p.years_exp == 0),
           "droy": ranked(lambda p: pos(p) in DEFENSE and p.years_exp == 0)}
    allpro = []
    for position, n in ALL_PRO:
        allpro.append((position, ranked(lambda p, x=position: pos(p) == x, n=n * 2)))
    out["all_pro"] = [(position, rows[:n], rows[n:2 * n]) for (position, n), (_, rows) in zip(ALL_PRO, allpro)]
    out["final"] = league.phase == "offseason"
    return out


def summary_lines(res: dict) -> list[str]:
    lines = []
    for key, label in AWARDS:
        if res[key]:
            w = res[key][0]
            lines.append(f"{label}: {w['name']} ({w['pos']}, {w['team']}) — {w['line']}")
    return lines
