"""화면용 데이터 조립 (CLI 출력 함수와 같은 계산을 dict로)."""
from __future__ import annotations

from ..domain.models import League, ScheduledGame
from ..season import standings as ST
from ..season.runner import ROUND_LABEL

POS_ORDER = ["QB", "RB", "FB", "WR", "TE", "OT", "OG", "C", "EDGE", "DT", "LB", "CB", "S", "K", "P", "LS"]


def grade_class(v: float) -> str:
    """능력치 1–20 등급 색 (PRD F2-5a)."""
    v = round(v)
    return ("g1" if v <= 5 else "g2" if v <= 9 else "g3" if v <= 12 else "g4" if v <= 15 else "g5" if v <= 17
            else "g6")


def record(league: League, abbr: str) -> str:
    return ST.Table.from_league(league).rec(abbr).text()


def next_game(league: League, team: str) -> ScheduledGame | None:
    games = [g for g in league.schedule if team in (g.home, g.away) and not g.played]
    return min(games, key=lambda g: (g.week, g.gameday or 0)) if games else None


def week_title(league: League, week: int | None = None) -> str:
    week = week or league.week
    games = league.games_in_week(week)
    kind = games[0].game_type if games else "REG"
    if league.phase == "offseason":
        return f"{league.season} 시즌 종료"
    return f"{league.season} 시즌 {week}주차" if kind == "REG" else f"{league.season} {ROUND_LABEL[kind]}"


def game_row(league: League, g: ScheduledGame, team: str | None = None) -> dict:
    d = {"id": g.game_id, "week": g.week, "type": g.game_type, "round": ROUND_LABEL.get(g.game_type, ""),
         "home": g.home, "away": g.away, "home_name": league.teams[g.home].name,
         "away_name": league.teams[g.away].name, "played": g.played, "hs": g.home_score, "as": g.away_score,
         "day": g.gameday.isoformat() if g.gameday else "", "neutral": g.neutral_site}
    if team and g.played and team in (g.home, g.away):
        mine = g.home_score if g.home == team else g.away_score
        theirs = g.away_score if g.home == team else g.home_score
        d["wl"] = "W" if mine > theirs else "L" if mine < theirs else "T"
    return d


def win_prob(league: League, home: str, away: str, neutral: bool = False) -> float | None:
    st = league.owner
    if st is None or not getattr(st, "power", None):
        return None
    from ..season.owner import win_prob as wp
    return wp(st.power, home, away, neutral)


def division_table(league: League, team: str) -> list[dict]:
    st = ST.compute(league)
    t = league.teams[team]
    started = any(g.played for g in league.schedule)
    seed_of = {x: i + 1 for s in st.seeds.values() for i, x in enumerate(s)} if started else {}
    out = []
    for abbr in st.divisions[(t.conference, t.division)]:
        r = st.rec(abbr)
        out.append({"abbr": abbr, "name": league.teams[abbr].name, "rec": r.text(), "pf": r.pf, "pa": r.pa,
                    "seed": seed_of.get(abbr), "me": abbr == team})
    return out
