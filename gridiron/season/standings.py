"""순위·타이브레이커·시드 (PRD F1-4·F1-5·F1-6). nflseedR의 NFL 공식 절차를 Python으로 옮겼다.

디비전 동률: 상대 전적 → 디비전 성적 → 공통 상대 → 컨퍼런스 성적 → SOV → SOS → 득실(컨퍼런스·공통·전체) → 동전.
와일드카드 동률: 같은 디비전 팀은 디비전 순위로 1팀만 남긴 뒤 상대 전적(2팀: 맞대결, 3팀+: 전승·전패만)
  → 컨퍼런스 성적 → 공통 상대(4경기 이상) → SOV → SOS → 득실 → 동전.
어느 단계에서든 일부 팀만 떨어지면 남은 팀으로 1단계부터 다시 한다 (공식 규칙). 동전은 시즌·팀 해시로 결정론적.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field

from ..domain.models import League, ScheduledGame

PLAYOFF_ROUNDS = ("WC", "DIV", "CON", "SB")


@dataclass
class Rec:
    w: int = 0
    l: int = 0     # noqa: E741
    t: int = 0
    pf: int = 0
    pa: int = 0

    def add(self, pf: int, pa: int) -> None:
        self.pf += pf
        self.pa += pa
        if pf > pa:
            self.w += 1
        elif pf < pa:
            self.l += 1
        else:
            self.t += 1

    @property
    def g(self) -> int:
        return self.w + self.l + self.t

    @property
    def pct(self) -> float:
        return (self.w + 0.5 * self.t) / self.g if self.g else 0.0

    @property
    def net(self) -> int:
        return self.pf - self.pa

    def text(self) -> str:
        return f"{self.w}-{self.l}" + (f"-{self.t}" if self.t else "")


@dataclass
class Table:
    league: League
    games: list[tuple[str, str, int, int]] = field(default_factory=list)   # (팀, 상대, 득점, 실점)

    @classmethod
    def from_league(cls, league: League, upto_week: int | None = None) -> "Table":
        tb = cls(league)
        for g in league.schedule:
            if g.game_type != "REG" or not g.played or (upto_week and g.week > upto_week):
                continue
            tb.games.append((g.home, g.away, g.home_score, g.away_score))
            tb.games.append((g.away, g.home, g.away_score, g.home_score))
        return tb

    def rec(self, team: str, opps=None) -> Rec:
        r = Rec()
        for t, o, pf, pa in self.games:
            if t == team and (opps is None or o in opps):
                r.add(pf, pa)
        return r

    def opponents(self, team: str) -> list[str]:
        return [o for t, o, *_ in self.games if t == team]

    def beaten(self, team: str) -> list[str]:
        return [o for t, o, pf, pa in self.games if t == team and pf > pa]

    def _combined(self, teams: list[str]) -> float:
        rs = [self.rec(x) for x in teams]
        g = sum(r.g for r in rs)
        return sum(r.w + 0.5 * r.t for r in rs) / g if g else 0.0

    def sov(self, team: str) -> float:
        return self._combined(self.beaten(team))

    def sos(self, team: str) -> float:
        return self._combined(self.opponents(team))

    def div_teams(self, team: str) -> set[str]:
        me = self.league.teams[team]
        return {a for a, t in self.league.teams.items() if t.conference == me.conference and t.division == me.division}

    def conf_teams(self, team: str) -> set[str]:
        conf = self.league.teams[team].conference
        return {a for a, t in self.league.teams.items() if t.conference == conf}


def _coin(season: int, team: str) -> float:
    return zlib.crc32(f"{season}:{team}".encode()) / 2**32


def _h2h(tb: Table, tied: list[str], mode: str) -> dict[str, float] | None:
    group = set(tied)
    if mode == "div" or len(tied) == 2:
        recs = {t: tb.rec(t, group - {t}) for t in tied}
        if any(r.g == 0 for r in recs.values()):
            return None
        return {t: r.pct for t, r in recs.items()}
    # 와일드카드 3팀+: 한 팀이 나머지 모두를 이겼거나 모두에게 졌을 때만
    for t in tied:
        others = group - {t}
        res = {o: tb.rec(t, {o}) for o in others}
        if all(r.g and r.w == r.g for r in res.values()):
            return {x: (1.0 if x == t else 0.0) for x in tied}
        if all(r.g and r.l == r.g for r in res.values()):
            return {x: (0.0 if x == t else 1.0) for x in tied}
    return None


def _common(tb: Table, tied: list[str], min_games: int) -> dict[str, Rec] | None:
    common = set.intersection(*(set(tb.opponents(t)) for t in tied)) - set(tied)
    if not common:
        return None
    recs = {t: tb.rec(t, common) for t in tied}
    if min(r.g for r in recs.values()) < min_games:
        return None
    return recs


def _steps(tb: Table, tied: list[str], mode: str):
    yield lambda: _h2h(tb, tied, mode)
    if mode == "div":
        yield lambda: {t: tb.rec(t, tb.div_teams(t) - {t}).pct for t in tied}
        yield lambda: (lambda c: {t: r.pct for t, r in c.items()} if c else None)(_common(tb, tied, 1))
        yield lambda: {t: tb.rec(t, tb.conf_teams(t) - {t}).pct for t in tied}
    else:
        yield lambda: {t: tb.rec(t, tb.conf_teams(t) - {t}).pct for t in tied}
        yield lambda: (lambda c: {t: r.pct for t, r in c.items()} if c else None)(_common(tb, tied, 4))
    yield lambda: {t: tb.sov(t) for t in tied}
    yield lambda: {t: tb.sos(t) for t in tied}
    yield lambda: {t: tb.rec(t, tb.conf_teams(t) - {t}).net for t in tied}
    yield lambda: (lambda c: {t: r.net for t, r in c.items()} if c else None)(_common(tb, tied, 1))
    yield lambda: {t: tb.rec(t).net for t in tied}
    yield lambda: {t: _coin(tb.league.season, t) for t in tied}


def _break(tb: Table, tied: list[str], mode: str, div_rank: dict[str, int] | None = None) -> str:
    """동률 팀 중 앞 순위 한 팀을 고른다."""
    if mode == "wc" and div_rank is not None:
        best: dict[str, str] = {}
        for t in tied:
            d = tb.league.teams[t].division
            if d not in best or div_rank[t] < div_rank[best[d]]:
                best[d] = t
        tied = list(best.values())
    if len(tied) == 1:
        return tied[0]
    for step in _steps(tb, tied, mode):
        scores = step()
        if scores is None:
            continue
        top = max(scores.values())
        lead = [t for t in tied if abs(scores[t] - top) < 1e-12]
        if len(lead) == 1:
            return lead[0]
        if len(lead) < len(tied):
            return _break(tb, lead, mode, div_rank)
    return tied[0]


def order(tb: Table, teams: list[str], mode: str, div_rank: dict[str, int] | None = None) -> list[str]:
    """승률 순으로 줄 세우고 동률은 공식 절차로 한 팀씩 뽑는다."""
    left = list(teams)
    out = []
    while left:
        best = max(tb.rec(t).pct for t in left)
        tied = [t for t in left if abs(tb.rec(t).pct - best) < 1e-12]
        pick = tied[0] if len(tied) == 1 else _break(tb, tied, mode, div_rank)
        out.append(pick)
        left.remove(pick)
    return out


@dataclass
class Standings:
    table: Table
    divisions: dict[tuple[str, str], list[str]]    # (컨퍼런스, 디비전) → 순위
    seeds: dict[str, list[str]]                     # 컨퍼런스 → 1–7 시드
    conference_order: dict[str, list[str]]          # 컨퍼런스 → 16팀 전체 순위

    def rec(self, team: str) -> Rec:
        return self.table.rec(team)


def compute(league: League, upto_week: int | None = None) -> Standings:
    tb = Table.from_league(league, upto_week)
    divisions, div_rank = {}, {}
    for conf in ("AFC", "NFC"):
        for div in ("East", "North", "South", "West"):
            teams = sorted(a for a, t in league.teams.items() if t.conference == conf and t.division == div)
            if not teams:
                continue
            ranked = order(tb, teams, "div")
            divisions[(conf, div)] = ranked
            div_rank.update({t: i for i, t in enumerate(ranked)})
    seeds, conf_order = {}, {}
    for conf in ("AFC", "NFC"):
        winners = [r[0] for (c, _), r in divisions.items() if c == conf]
        rest = [t for (c, _), r in divisions.items() if c == conf for t in r[1:]]
        w = order(tb, winners, "wc", div_rank)
        r = order(tb, rest, "wc", div_rank)
        seeds[conf] = w + r[:3]
        conf_order[conf] = w + r
    return Standings(tb, divisions, seeds, conf_order)


# ── 플레이오프 (F1-4) ─────────────────────────────────────────
def _pgame(league: League, rnd: str, home: str, away: str, week: int, idx: int, neutral: bool = False) -> ScheduledGame:
    from datetime import timedelta
    last = max((g.gameday for g in league.schedule if g.gameday), default=None)
    day = last + timedelta(days=7) if last else None
    stadium = None if neutral else next((g.stadium for g in league.schedule if g.home == home and g.stadium), None)
    roof = "dome" if neutral else next((g.roof for g in league.schedule if g.home == home and g.roof), None)
    surface = None if neutral else next((g.surface for g in league.schedule if g.home == home and g.surface), None)
    return ScheduledGame(game_id=f"{league.season}_{week:02d}_{away}_{home}", season=league.season, week=week,
                         game_type=rnd, home=home, away=away, gameday=day, stadium=stadium, roof=roof,
                         surface=surface, neutral_site=neutral)


def reg_weeks(league: League) -> int:
    return max((g.week for g in league.schedule if g.game_type == "REG"), default=18)


def _winner(g: ScheduledGame) -> str:
    return g.home if g.home_score > g.away_score else g.away


def next_round(league: League) -> list[ScheduledGame]:
    """현재까지 결과로 다음 플레이오프 라운드 경기를 만든다. 만들 것이 없으면 빈 목록.

    정규시즌·직전 라운드가 모두 끝나야 만든다. 와일드카드 2–7·3–6·4–5, 이후 재시딩(최고 시드가 최저 시드와).
    """
    base = reg_weeks(league)
    if any(not g.played for g in league.schedule):
        return []
    done = {g.game_type for g in league.schedule}
    st = compute(league)
    seed_of = {t: i + 1 for conf in st.seeds for i, t in enumerate(st.seeds[conf])}
    games: list[ScheduledGame] = []
    if "WC" not in done:
        for conf in ("AFC", "NFC"):
            s = st.seeds[conf]
            for i, (a, b) in enumerate(((1, 6), (2, 5), (3, 4))):
                games.append(_pgame(league, "WC", s[a], s[b], base + 1, i))
    elif "DIV" not in done or "CON" not in done:
        rnd, prev, week = ("DIV", "WC", base + 2) if "DIV" not in done else ("CON", "DIV", base + 3)
        for conf in ("AFC", "NFC"):
            alive = [_winner(g) for g in league.schedule if g.game_type == prev and league.teams[g.home].conference == conf]
            if rnd == "DIV":
                alive.append(st.seeds[conf][0])
            alive.sort(key=lambda t: seed_of[t])
            pairs = [(alive[0], alive[-1]), (alive[1], alive[2])] if rnd == "DIV" else [(alive[0], alive[1])]
            for i, (h, a) in enumerate(pairs):
                games.append(_pgame(league, rnd, h, a, week, i))
    elif "SB" not in done:
        champs = {league.teams[_winner(g)].conference: _winner(g) for g in league.schedule if g.game_type == "CON"}
        # 슈퍼볼 홈 표기: 홀수 회차(= 짝수 해 시즌) AFC, 짝수 회차 NFC (실제 관례)
        h, a = (champs["AFC"], champs["NFC"]) if league.season % 2 == 0 else (champs["NFC"], champs["AFC"])
        games.append(_pgame(league, "SB", h, a, base + 4, 0, neutral=True))
    return games


def champion(league: League) -> str | None:
    sb = [g for g in league.schedule if g.game_type == "SB" and g.played]
    return _winner(sb[0]) if sb else None


def eliminated_round(league: League) -> dict[str, str]:
    """팀 → 시즌을 마친 단계 (REG | WC | DIV | CON | SB | CHAMP)."""
    out = {a: "REG" for a in league.teams}
    for g in league.schedule:
        if g.game_type in PLAYOFF_ROUNDS and g.played:
            loser = g.away if _winner(g) == g.home else g.home
            out[loser] = g.game_type
            if g.game_type == "SB":
                out[_winner(g)] = "CHAMP"
    return out


def draft_order(league: League) -> list[str]:
    """드래프트 순서 (F1-6): 플레이오프 탈락 팀은 승률 낮은 순(동률 SOS 낮은 순), 진출 팀은 탈락 라운드 순."""
    st = compute(league)
    tb = st.table
    playoff = {t for s in st.seeds.values() for t in s}
    stage = eliminated_round(league)
    rank = {"REG": 0, "WC": 1, "DIV": 2, "CON": 3, "SB": 4, "CHAMP": 5}
    key = lambda t: (t in playoff, rank[stage[t]], tb.rec(t).pct, tb.sos(t), _coin(league.season, t))  # noqa: E731
    return sorted(league.teams, key=key)
