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


def player_profile(league: League, p, observer: str | None, path) -> dict:
    """선수 프로필 (S4): CLI `player`와 같은 계산. 다른 팀 선수는 파악도 범위."""
    from ..domain.attributes import ATTRIBUTES, HIDDEN_KEYS, grade_label
    from ..domain.positions import Position
    from ..ratings.position_rating import position_rating
    from ..ratings.roles import role_ratings
    from ..season import knowledge as KN
    own = p.team == observer
    k = KN.knowledge(league, p, observer)
    lo, hi = KN.pr_range(league, p, observer)
    groups: dict[str, list] = {}
    labels = {"physical": "신체", "mental": "정신", "passing": "패싱", "ball_carrier": "볼 캐리어", "receiving": "리시빙",
              "blocking": "블로킹", "defense": "수비", "special": "스페셜팀"}
    for d in ATTRIBUTES.values():
        if d.key in HIDDEN_KEYS:
            continue
        r = KN.attr_range(league, p, d.key, observer)
        groups.setdefault(labels.get(d.group, d.group), []).append(
            {"label": d.label_ko, "lo": r[0], "hi": r[1], "mid": (r[0] + r[1]) / 2})
    special = (Position.K, Position.P, Position.LS)
    top = sorted(((pos, position_rating(p, pos)) for pos in Position if pos == p.position or pos not in special),
                 key=lambda x: -x[1])[:4]
    rr = role_ratings(p)
    best = max(rr, key=lambda key: rr[key][1]) if rr else None
    roles = [{"name": n, "range": KN.fmt_range(*KN.value_range(league, p, observer, v, "role:" + key)),
              "best": key == best and own, "v": v} for key, (n, v) in rr.items()]
    hidden = KN.hidden_comments(p, max(0, league.week - 1)) if own else None
    hist = []
    if path is not None:
        from sqlmodel import Session, select

        from ..db import schema as S
        from ..db.store import engine_for
        with Session(engine_for(path)) as s:
            hist = [{"season": h.season, "week": h.week, "type": h.type, "missed": h.missed, "status": h.status}
                    for h in s.exec(select(S.InjuryRow).where(S.InjuryRow.player_id == p.id).order_by(S.InjuryRow.id))]
    return {"p": p, "own": own, "knowledge": k, "pr": KN.fmt_range(lo, hi), "pr_lo": lo, "pr_hi": hi,
            "stars": KN.star_text(lo, hi), "groups": groups, "prs": [(pos.value, KN.fmt_range(*KN.pr_range(
                league, p, observer, pos))) for pos, _ in top], "roles": roles,
            "role_grade": grade_label(rr[best][1]) if best and own else None, "hidden": hidden, "injuries": hist,
            "age": p.age_on(league.season_start())}


def season_stats(path, pid: str, season: int) -> dict:
    from sqlmodel import Session, select

    from ..db import schema as S
    from ..db.store import engine_for
    tot: dict = {}
    with Session(engine_for(path)) as s:
        q = select(S.PlayerGameStatsRow, S.GameRow).where(S.PlayerGameStatsRow.player_id == pid) \
            .where(S.GameRow.id == S.PlayerGameStatsRow.game_id).where(S.GameRow.season == season)
        from ..season.game_report import derive
        for r, _ in s.exec(q):
            for k, v in derive(r.stats).items():
                if isinstance(v, (int, float)):
                    tot[k] = tot.get(k, 0) + v
    return tot


STAT_LABELS = [("gp", "경기"), ("snaps", "스냅"), ("pssCmp", "완성"), ("pss", "시도"), ("pssYds", "패싱야드"),
               ("pssTD", "패싱TD"), ("pssInt", "INT"), ("pssSk", "색 허용"), ("rus", "러싱"), ("rusYds", "러싱야드"),
               ("rusTD", "러싱TD"), ("tgt", "타깃"), ("rec", "리셉션"), ("recYds", "리시빙야드"), ("recTD", "리시빙TD"),
               ("defTck", "태클"), ("defSk", "색"), ("defInt", "INT"), ("defPssDef", "패스방어"), ("defFmbFrc", "강제 펌블"),
               ("fg", "FG 성공"), ("fga", "FG 시도"), ("pnt", "펀트"), ("pntYds", "펀트야드")]


def vis_color(team) -> str:
    """어두운 배경에서 보이는 팀 색 (주 색이 너무 어두우면 보조 색, 그것도 어두우면 회색)."""
    def lum(h: str) -> float:
        h = h.lstrip("#")
        if len(h) != 6:
            return 0.5
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    for c in (team.color, team.color2):
        if c and lum(c) > 0.12:
            return c
    return "#9aa5b1"
