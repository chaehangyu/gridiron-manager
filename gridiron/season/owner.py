"""구단주 목표·신뢰도·평가 (PRD F12, M5d).

기대치(F12-1): 실제 경기 엔진으로 이번 시즌 일정을 몇 번 돌려 팀 파워 레이팅(득실차 회귀)을 구하고, 그 레이팅으로
시즌 전체를 200회 몬테카를로 시뮬(공식 타이브레이커·플레이오프 포함)해 예상 승수 분포와 플레이오프 확률을 낸다.
엔진 시즌 한 번(약 30초 × 반복 수)이면 되므로 200회를 전부 엔진으로 돌리는 것과 같은 기대치를 빠르게 얻는다.

신뢰도(F12-4): 시작 60. 경기마다 K × (결과 − 경기 전 예상 승률). 주간 목표 진행률을 소폭 반영.
평가(F12-6): 주 목표 50% + 보조 목표 25% + 신뢰도 25% → A–F. 해고(F12-7): 20 미만 경고 2회 뒤 또 20 미만이면
시즌 중 해고, 시즌 말 F면 해고. 리그 설정 `owner.firing`으로 끌 수 있다.
"""
from __future__ import annotations

import math
import random
import zlib
from dataclasses import asdict, dataclass, field

import numpy as np

from ..domain.models import League, ScheduledGame
from . import standings as ST

MARGIN_SD = 13.5          # NFL 경기 득실차 표준편차 (예상 대비). 파워 레이팅이 엔진 잔차로 덮어쓴다
RIDGE = 5.0
K_CONF = 12.0             # 신뢰도 변화 배율
START_CONF = 60.0
TIERS = {"contender": "우승 후보", "playoff": "플레이오프 경쟁", "middle": "중위권", "rebuild": "재건"}
MAIN_GOAL_LABEL = {"conf_final": "컨퍼런스 결승 진출", "div_round": "디비저널 라운드 진출",
                   "playoffs": "플레이오프 진출"}
SUB_GOALS = {"division": "디비전 라이벌전 승률 5할 이상", "offense": "득점 리그 10위 이내",
             "defense": "실점 리그 10위 이내", "health": "부상 결장 경기 수 리그 평균 이하",
             "home": "홈 경기 승률 5할 이상", "rookies": "신인 출전 스냅 확보 (팀 스냅의 8% 이상)"}


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ── 파워 레이팅 (엔진 기반) ─────────────────────────────────────
def power_ratings(league: League, reps: int = 2, seed: int = 0) -> dict:
    """이번 시즌 정규시즌 일정을 엔진으로 reps번 돌려 득실차 = 홈 이점 + r_home − r_away 를 릿지 회귀로 푼다."""
    from ..engine.api import simulate
    teams = sorted(league.teams)
    idx = {t: i for i, t in enumerate(teams)}
    rows, y = [], []
    games = [g for g in league.schedule if g.game_type == "REG"]
    for r in range(reps):
        for g in games:
            copy = ScheduledGame(g.game_id, g.season, g.week, g.game_type, g.home, g.away, g.gameday, g.stadium,
                                 g.roof, g.surface, g.neutral_site)
            out = simulate(league, copy, seed=zlib.crc32(f"pw{seed}:{r}:{g.game_id}".encode()), play_by_play=False,
                           injuries=False)
            x = np.zeros(len(teams) + 1)
            x[idx[g.home]], x[idx[g.away]], x[-1] = 1, -1, 0 if g.neutral_site else 1
            rows.append(x)
            y.append(out.home_score - out.away_score)
    X, Y = np.array(rows), np.array(y, dtype=float)
    # 릿지: 경기 잡음 분산 ÷ 팀 실력 분산 (13.5² / 4.5² ≈ 9) — 적은 반복에서 생기는 레이팅 과장을 줄인다
    A = X.T @ X + RIDGE * np.diag([1.0] * len(teams) + [0.0])
    beta = np.linalg.solve(A, X.T @ Y)
    resid = Y - X @ beta
    r = beta[:-1] - beta[:-1].mean()
    return {"ratings": {t: round(float(r[idx[t]]), 2) for t in teams}, "hfa": round(float(beta[-1]), 2),
            "sd": round(float(resid.std()), 2), "games": len(Y)}


def win_prob(power: dict, home: str, away: str, neutral: bool = False) -> float:
    r = power["ratings"]
    m = r[home] - r[away] + (0 if neutral else power["hfa"])
    return _phi(m / power.get("sd", MARGIN_SD))


# ── 200회 시즌 투영 ─────────────────────────────────────────
def project(league: League, power: dict, n: int = 200, seed: int = 0) -> dict[str, dict]:
    rng = random.Random(seed)
    teams = sorted(league.teams)
    wins = {t: [] for t in teams}
    made = {t: 0 for t in teams}
    div_round = {t: 0 for t in teams}
    conf_final = {t: 0 for t in teams}
    champ = {t: 0 for t in teams}
    reg = [g for g in league.schedule if g.game_type == "REG"]
    sim = League(season=league.season, teams=league.teams, players={}, schedule=[])
    # 레이팅 추정 불확실성: 시즌마다 레이팅을 표준오차만큼 흔든다 (엔진 반복 수가 적을수록 크다)
    per_team = power.get("games", 544) * 2 / max(1, len(teams))
    se = power.get("sd", MARGIN_SD) / math.sqrt(per_team + RIDGE)
    for _ in range(n):
        pw = {**power, "ratings": {t: v + rng.gauss(0, se) for t, v in power["ratings"].items()}}
        sched = []
        for g in reg:
            if g.played:
                hs, as_ = g.home_score, g.away_score
            else:
                p = win_prob(pw, g.home, g.away, g.neutral_site)
                hs, as_ = (1, 0) if rng.random() < p else (0, 1)
            sched.append(ScheduledGame(g.game_id, g.season, g.week, "REG", g.home, g.away, home_score=hs,
                                       away_score=as_))
        sim.schedule = sched
        st = ST.compute(sim)
        for t in teams:
            wins[t].append(st.rec(t).w + 0.5 * st.rec(t).t)
        finalists = []
        for conf, seeds in st.seeds.items():
            for t in seeds:
                made[t] += 1
            alive = _play_bracket(seeds, pw, rng)
            for t in alive["div"]:
                div_round[t] += 1
            for t in alive["con"]:
                conf_final[t] += 1
            finalists.append(alive["champ"])
        a, b = finalists
        champ[a if rng.random() < win_prob(pw, a, b, neutral=True) else b] += 1
    out = {}
    for t in teams:
        w = np.array(wins[t])
        out[t] = {"wins_mean": round(float(w.mean()), 2), "wins_sd": round(float(w.std()), 2),
                  "wins_q40": float(np.floor(np.percentile(w, 40))),
                  "p_playoffs": round(made[t] / n, 3), "p_div_round": round(div_round[t] / n, 3),
                  "p_conf_final": round(conf_final[t] / n, 3),
                  "p_title": round(champ[t] / n, 3)}
    return out


def _play_bracket(seeds: list[str], power: dict, rng: random.Random) -> dict:
    def play(h, a):
        return h if rng.random() < win_prob(power, h, a) else a
    rank = {t: i for i, t in enumerate(seeds)}
    wc = [play(seeds[1], seeds[6]), play(seeds[2], seeds[5]), play(seeds[3], seeds[4])]
    alive = sorted([seeds[0]] + wc, key=rank.get)
    con = sorted([play(alive[0], alive[3]), play(alive[1], alive[2])], key=rank.get)
    champ = play(con[0], con[1])
    return {"div": alive, "con": con, "champ": champ}


def main_goal(proj: dict) -> str:
    """주 목표 (F12-2): 달성 확률이 절반 이상인 가장 높은 목표. 그 아래는 승수 목표 (60% 달성 수준)."""
    if proj["p_conf_final"] >= 0.5:
        return "conf_final"
    if proj["p_div_round"] >= 0.5:
        return "div_round"
    if proj["p_playoffs"] >= 0.55:
        return "playoffs"
    return f"wins:{int(max(3, proj['wins_q40']))}"


def goal_label(goal: str) -> str:
    if goal.startswith("wins:"):
        n = int(goal.split(":")[1])
        return f"{n}승 이상" + (" (승률 5할)" if n == 9 else "")
    return MAIN_GOAL_LABEL[goal]


def tier_of(proj: dict) -> str:
    if proj["p_conf_final"] >= 0.3:
        return "contender"
    if proj["p_playoffs"] >= 0.45:
        return "playoff"
    if proj["wins_mean"] >= 7.0:
        return "middle"
    return "rebuild"


# ── 목표·신뢰도 ────────────────────────────────────────────
@dataclass
class OwnerState:
    team: str
    season: int
    tier: str
    wins_mean: float
    wins_sd: float
    main_goal: str
    sub_goals: list[str]
    confidence: float = START_CONF
    warnings: int = 0
    fired: bool = False
    grade: str | None = None
    history: list = field(default_factory=list)      # [(week, value, reason)]
    inbox: list = field(default_factory=list)        # [{"week", "kind", "text"}]
    power: dict = field(default_factory=dict)
    projection: dict = field(default_factory=dict)   # 우리 팀 투영값
    firing: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "OwnerState":
        return cls(**d)


def pick_sub_goals(team: str, season: int, tier: str) -> list[str]:
    rng = random.Random(zlib.crc32(f"owner:{season}:{team}".encode()))
    cands = list(SUB_GOALS)
    if tier == "rebuild":
        cands += ["rookies", "rookies"]          # 재건 팀은 신인 기용 목표가 잘 나온다
    else:
        cands = [c for c in cands if c != "rookies"]
    out = []
    while len(out) < 2:
        c = rng.choice(cands)
        if c not in out:
            out.append(c)
    return out


def start_season(league: League, team: str, power: dict | None = None, projection: dict | None = None,
                 reps: int = 2, n: int = 200) -> OwnerState:
    power = power or power_ratings(league, reps=reps, seed=league.season)
    projection = projection or project(league, power, n=n, seed=league.season)
    pr = projection[team]
    tier = tier_of(pr)
    st = OwnerState(team=team, season=league.season, tier=tier, wins_mean=pr["wins_mean"], wins_sd=pr["wins_sd"],
                    main_goal=main_goal(pr), sub_goals=pick_sub_goals(team, league.season, tier),
                    power=power, projection=pr)
    st.inbox.append({"week": 0, "kind": "goal",
                     "text": f"구단주: 올해 우리는 {TIERS[tier]}입니다 (예상 {pr['wins_mean']:.1f}승). "
                             f"목표는 {goal_label(st.main_goal)}. 그리고 {SUB_GOALS[st.sub_goals[0]]}, "
                             f"{SUB_GOALS[st.sub_goals[1]]}."})
    st.history.append((0, START_CONF, "시즌 시작"))
    return st


def after_game(st: OwnerState, league: League, game: ScheduledGame) -> float:
    """경기 결과 → 신뢰도 변화 (경기 전 예상 승률 대비)."""
    if st.fired or st.team not in (game.home, game.away):
        return 0.0
    p_home = win_prob(st.power, game.home, game.away, game.neutral_site)
    p = p_home if game.home == st.team else 1 - p_home
    mine = game.home_score if game.home == st.team else game.away_score
    theirs = game.away_score if game.home == st.team else game.home_score
    res = 1.0 if mine > theirs else 0.5 if mine == theirs else 0.0
    k = K_CONF * (1.5 if game.game_type != "REG" else 1.0)
    delta = k * (res - p)
    st.confidence = max(0.0, min(100.0, st.confidence + delta))
    opp = game.away if game.home == st.team else game.home
    why = f"{'승' if res == 1 else '무' if res == 0.5 else '패'} vs {opp} (예상 승률 {p * 100:.0f}%)"
    st.history.append((game.week, round(st.confidence, 1), why))
    _messages(st, game.week, delta, p, res)
    return delta


def _messages(st: OwnerState, week: int, delta: float, p: float, res: float) -> None:
    if res == 1 and p < 0.35:
        st.inbox.append({"week": week, "kind": "praise", "text": "구단주: 아무도 기대하지 않은 승리였습니다. 훌륭합니다."})
    elif res == 0 and p > 0.7:
        st.inbox.append({"week": week, "kind": "concern", "text": "구단주: 이겨야 할 경기를 놓쳤습니다. 실망스럽군요."})
    if st.confidence < 20 and st.firing:
        st.warnings += 1
        if st.warnings > 2:
            st.fired = True
            st.inbox.append({"week": week, "kind": "fired",
                             "text": "구단주: 더는 기다릴 수 없습니다. 오늘부로 감독직에서 물러나 주십시오."})
        else:
            st.inbox.append({"week": week, "kind": "warning",
                             "text": f"구단주: 마지막 경고입니다 ({st.warnings}/2). 반등하지 못하면 결단하겠습니다."})
    elif st.confidence < 40 and delta < 0:
        st.inbox.append({"week": week, "kind": "concern", "text": "구단주: 팀이 기대에 못 미치고 있습니다."})


def weekly_progress(st: OwnerState, league: League, week: int) -> None:
    """주간 목표 진행률 반영 (F12-4): 남은 일정 기준 주 목표 달성 가능성이 기대보다 높으면 +, 낮으면 −."""
    if st.fired:
        return
    tb = ST.Table.from_league(league)
    r = tb.rec(st.team)
    if r.g == 0:
        return
    pace = (r.w + 0.5 * r.t) / r.g * 17
    drift = max(-1.0, min(1.0, (pace - st.wins_mean) / 4))
    st.confidence = max(0.0, min(100.0, st.confidence + drift))


# ── 시즌 말 평가 ───────────────────────────────────────────
def goal_results(st: OwnerState, league: League, path=None) -> dict[str, bool]:
    tb = ST.Table.from_league(league)
    me = st.team
    r = tb.rec(me)
    stage = ST.eliminated_round(league)
    seeds = ST.compute(league).seeds
    in_po = any(me in s for s in seeds.values())
    res = {st.main_goal: achieved(st.main_goal, me, r, stage, in_po)}
    teams = list(league.teams)
    for g in st.sub_goals:
        if g == "division":
            res[g] = tb.rec(me, tb.div_teams(me) - {me}).pct >= 0.5
        elif g == "offense":
            res[g] = sorted(teams, key=lambda t: -tb.rec(t).pf).index(me) < 10
        elif g == "defense":
            res[g] = sorted(teams, key=lambda t: tb.rec(t).pa).index(me) < 10
        elif g == "home":
            homes = [x for x in league.schedule if x.game_type == "REG" and x.played and x.home == me]
            res[g] = sum(x.home_score > x.away_score for x in homes) >= len(homes) / 2
        elif g == "health":
            missed = _missed_games(league, path)
            res[g] = missed.get(me, 0) <= (sum(missed.values()) / max(1, len(teams)))
        elif g == "rookies":
            res[g] = _rookie_share(league, me, path) >= 0.08
    return res


def _missed_games(league: League, path) -> dict[str, int]:
    out: dict[str, int] = {}
    if path is None:
        for p in league.players.values():
            if p.injury and p.team:
                out[p.team] = out.get(p.team, 0) + p.injury.missed
        return out
    from sqlmodel import Session, select

    from ..db import schema as S
    from ..db.store import engine_for
    with Session(engine_for(path)) as s:
        for r in s.exec(select(S.InjuryRow).where(S.InjuryRow.season == league.season)):
            p = league.players.get(r.player_id)
            if p and p.team:
                out[p.team] = out.get(p.team, 0) + r.missed
    return out


def _rookie_share(league: League, team: str, path) -> float:
    if path is None:
        return 0.0
    from sqlmodel import Session, select

    from ..db import schema as S
    from ..db.store import engine_for
    tot = rook = 0.0
    with Session(engine_for(path)) as s:
        for r in s.exec(select(S.PlayerGameStatsRow).where(S.PlayerGameStatsRow.team == team)):
            n = r.stats.get("snaps", 0)
            tot += n
            p = league.players.get(r.player_id)
            if p and p.years_exp == 0:
                rook += n
    return rook / tot if tot else 0.0


def achieved(goal: str, team: str, rec, stage: dict, in_playoffs: bool) -> bool:
    if goal.startswith("wins:"):
        return rec.w + 0.5 * rec.t >= int(goal.split(":")[1])
    return {"conf_final": stage.get(team) in ("CON", "SB", "CHAMP"),
            "div_round": stage.get(team) in ("DIV", "CON", "SB", "CHAMP"), "playoffs": in_playoffs}[goal]


def season_review(st: OwnerState, league: League, path=None) -> tuple[str, dict]:
    res = goal_results(st, league, path)
    score = 50 * res[st.main_goal] + 12.5 * sum(res[g] for g in st.sub_goals) + 0.25 * st.confidence
    grade = "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 35 else "F"
    st.grade = grade
    if grade == "F" and st.firing:
        st.fired = True
    text = {"A": "기대 이상의 시즌이었습니다. 앞으로도 잘 부탁합니다.", "B": "좋은 시즌이었습니다.",
            "C": "무난했지만 더 나아져야 합니다.", "D": "실망스러운 시즌입니다. 내년이 마지막 기회입니다.",
            "F": "목표에 한참 못 미쳤습니다. 결별하겠습니다."}[grade]
    st.inbox.append({"week": league.week, "kind": "review", "text": f"구단주 시즌 평가 {grade}: {text}"})
    return grade, res
