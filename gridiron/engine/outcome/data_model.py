"""실측 기준 분포 결과 모델 (ENGINE_DESIGN §3, §5 — PRD M2).

플레이 한 번의 흐름
1. 콜 (call_play): 공격은 상황별 실측 비율로 퍼스넬·플레이 패밀리를, 수비는 퍼스넬을 보고 커버리지·블리츠·박스를 고른다.
   M4에서 이 부분이 전술 설정 + 경기 중 학습 코디네이터로 바뀐다.
2. 패스: 압박 → (색 | 스크램블 | 스로어웨이) → 실제 던진 깊이 → 완성·INT·에어 야드·YAC
   런: (패밀리 × 필드 구역 × 박스 × 거리) 분포
3. 능력치 차이 Δ로 확률은 로짓 이동, 야드는 분위수 이동.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from ...baseline import tables as T
from ...config import load
from .. import adjust as A
from ..ai import decisions as D
from .base import PassPlan, RunPlan

if TYPE_CHECKING:
    from ..skeleton.game import GameSim
    from ..skeleton.types import PlayerGameSim

OFF_FORMATIONS = {
    "11": {"QB": 1, "RB": 1, "WR": 3, "TE": 1, "OL": 5},
    "12": {"QB": 1, "RB": 1, "WR": 2, "TE": 2, "OL": 5},
    "21": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "OL": 5},
    "13": {"QB": 1, "RB": 1, "WR": 1, "TE": 3, "OL": 5},
    "22": {"QB": 1, "RB": 2, "WR": 1, "TE": 2, "OL": 5},
    "10": {"QB": 1, "RB": 1, "WR": 4, "OL": 5},
}
DEF_FORMATIONS = {
    ("4-3", "base"): {"DL": 4, "LB": 3, "CB": 2, "S": 2},
    ("4-3", "nickel"): {"DL": 4, "LB": 2, "CB": 3, "S": 2},
    ("4-3", "dime"): {"DL": 4, "LB": 1, "CB": 4, "S": 2},
    ("3-4", "base"): {"DL": 5, "LB": 2, "CB": 2, "S": 2},   # 3-4의 OLB는 엔진에서 DL 그룹
    ("3-4", "nickel"): {"DL": 4, "LB": 2, "CB": 3, "S": 2},
    ("3-4", "dime"): {"DL": 4, "LB": 1, "CB": 4, "S": 2},
}
TARGET_POS_WEIGHT = {
    "screen": {"RB": 1.2, "WR": 1.0, "TE": 0.5},
    "quick": {"WR": 1.0, "TE": 0.8, "RB": 0.6},
    "inter": {"WR": 1.0, "TE": 0.8, "RB": 0.2},
    "deep": {"WR": 1.0, "TE": 0.35, "RB": 0.05},
}


@dataclass
class Call:
    kind: str                 # pass | run
    personnel: str
    def_personnel: str
    family: str               # 패스: screen/quick/inter/deep, 런: inside/outside/sneak
    play_action: bool
    coverage: str
    blitz: int
    box: str
    dd: str
    zone: str
    formation: dict
    intent: str | None = None     # 패스 의도 깊이 (실제 던진 깊이와 다를 수 있음)


@lru_cache(maxsize=1)
def _params() -> dict:
    return load("engine")


def dd_class(down: int, togo: float) -> str:
    if down == 1:
        return "1st"
    if down == 2:
        return "2s" if togo <= 3 else ("2m" if togo <= 7 else "2l")
    return f"{min(down, 4)}" + ("s" if togo <= 2 else ("m" if togo <= 6 else "l"))


def zone_of(yardline_100: float) -> str:
    if yardline_100 >= 90:
        return "backed"
    if yardline_100 > 20:
        return "open"
    if yardline_100 > 5:
        return "red"
    return "goal"


class DataOutcome:
    name = "data"

    def __init__(self) -> None:
        p = _params()
        self.beta = p["beta"]
        self.home_adv = p["home_advantage"]
        self.fumble_per_touch = p["fumble_per_touch"]
        self.intent = p["intent_to_depth"]
        self.center = p.get("center", {})
        self.depth_ratio_power = p.get("depth_ratio_power", 1.0)
        self._punt_row = None

    # ── 공통 ──────────────────────────────────────────────
    def _home(self, g: "GameSim") -> float:
        """홈 공격이면 +, 원정 공격이면 − (중립 경기 0)."""
        if g.neutral_site:
            return 0.0
        return self.home_adv if g.o == 0 else -self.home_adv

    def _on(self, g: "GameSim", t: int, *positions: str) -> list["PlayerGameSim"]:
        out = []
        for pos in positions:
            out.extend(g.playersOnField[t].get(pos) or [])
        return out

    def _choose(self, g: "GameSim", dist: dict[str, float]) -> str:
        return T.choose(dist, g.rng.random())

    # ── 플레이 선택 ───────────────────────────────────────
    def prob_pass(self, g: "GameSim") -> float:
        pts_down = g.team[g.d].stat["pts"] - g.team[g.o].stat["pts"]
        quarter = len(g.team[0].stat["ptsQtrs"])
        if g.scrimmage < 97 and quarter >= g.num_periods and (
            (quarter > g.num_periods and pts_down > 0) or (pts_down > 0 and g.clock <= 2)
            or (pts_down > 8 and g.clock <= 3) or (pts_down > 16 and g.clock <= 4) or (pts_down > 24 and g.clock <= 6)
        ):
            return 0.98 * g.settings.pass_factor
        game_sec, half_sec = D.clock_state(g)
        yl = 100 - g.scrimmage
        wp = D.wp_for(g, g.o, -pts_down, g.down, g.toGo, yl)
        return D.M.xpass(g.down, g.toGo, yl, -pts_down, game_sec, half_sec, wp) * g.settings.pass_factor

    def call_play(self, g: "GameSim", kind: str) -> Call:
        yl = 100 - g.scrimmage
        dd, zone = dd_class(g.down, g.toGo), zone_of(yl)
        pers = self._choose(g, T.lookup("personnel", kind, dd))
        front = getattr(g.team[g.d], "front", "4-3")
        dpers = self._choose(g, T.lookup("def_personnel", pers))
        intent = None
        if kind == "pass":
            family = self._choose(g, self._intent_mix(dd, zone))
            intent = family
            pa = family != "screen" and g.rng.random() < T.lookup("pa_rate", dd, zone)
        else:
            family = self._choose(g, T.lookup("run_family", dd, zone))
            if family == "sneak" and g.toGo > 2:
                family = "inside"
            pa = False
        cov = self._choose(g, T.lookup("coverage", dd, pers))
        blitz = 1 if g.rng.random() < T.lookup("blitz", cov, dd) else 0
        box = self._choose(g, T.lookup("box", kind, dd, pers, blitz))
        formation = {"off": OFF_FORMATIONS[pers], "def": DEF_FORMATIONS[(front, dpers)]}
        return Call(kind, pers, dpers, family, pa, cov, blitz, box, dd, zone, formation, intent)

    @lru_cache(maxsize=64)
    def _intent_mix(self, dd: str, zone: str) -> dict[str, float]:
        """실측 표는 '실제 던진 깊이' 비율이다. 체크다운 전환(intent_to_depth)을 역으로 풀어 '의도한 깊이' 비율을 구한다."""
        import numpy as np
        realized = T.lookup("pass_depth", dd, zone)
        order = ["screen", "quick", "inter", "deep"]
        M = np.array([[self.intent[i].get(j, 0.0) for j in order] for i in order])
        r = np.array([realized.get(k, 0.0) for k in order])
        x = np.clip(np.linalg.solve(M.T, r), 0.0, None)
        x = x / x.sum()
        return {k: float(v) for k, v in zip(order, x)}

    # ── 패스 ──────────────────────────────────────────────
    def pass_play(self, g: "GameSim") -> PassPlan:
        rng, o, d = g.rng, g.o, g.d
        call: Call = g.call or self.call_play(g, "pass")
        N = g.norms
        qb = g.getTopPlayerOnField(o, "QB")
        plan = PassPlan(extra={"call": call.family, "pa": call.play_action, "cov": call.coverage,
                               "blitz": call.blitz, "pers": call.personnel})

        if rng.random() < 0.75 and rng.random() < g.probFumble(qb) * 0.5:
            plan.qb_fumble = True
            plan.qb_fumble_yds = rng.rand_int(-1, -10)
            return plan

        # 1) 압박
        blockers = self._on(g, o, "OL")
        rushers = self._on(g, d, "DL") + (self._on(g, d, "LB")[:1] if call.blitz else [])
        c = self.center
        d_rush = A.top_mean(rushers, A.RUSH, N, 4 + call.blitz) - A.unit(blockers, A.PASS_BLOCK, N) - c.get("rush", 0.0)
        passing_down = 1 if call.dd in ("2l", "3m", "3l", "4m", "4l") else 0
        p_press = T.lookup("pressure", call.coverage, call.blitz, passing_down)
        p_press = T.logit_shift(p_press, self.beta["pressure"] * d_rush)
        pressure = 1 if rng.random() < p_press else 0
        plan.extra["pressure"] = pressure
        plan.pbw = {p: {"type": "OL", "won": True} for p in blockers}
        if pressure and blockers:
            loser = min(blockers, key=lambda p: A.mix(p, A.PASS_BLOCK, N) + rng.random() * 1.5)
            plan.pbw[loser] = {"type": "OL", "won": False}

        # 2) 드롭백 분기
        br = T.lookup("dropback_branch", pressure, call.blitz)
        qb_pocket = A.mix(qb, A.POCKET, N) - c.get("pocket", 0.0)
        qb_move = A.mix(qb, A.MOBILITY, N) - c.get("mobility", 0.0)
        p_sack = T.logit_shift(max(br["sack"], 1e-4), -self.beta["sack"] * qb_pocket) if pressure else br["sack"]
        p_scr = T.logit_shift(max(br["scramble"], 1e-4), self.beta["scramble"] * qb_move)
        u = rng.random()
        if u < p_sack and rng.random() < 2 * T.tables()["sack_fumble_lost"]:
            plan.qb_fumble = True  # 스트립 색 (절반은 공격이 회복)
            plan.qb_fumble_yds = round(T.sample_quantile(T.tables()["sack_yards"], rng.random()))
            return plan
        if u < p_sack:
            plan.sack = True
            plan.extra["sack_yds"] = round(T.sample_quantile(T.tables()["sack_yards"], rng.random()))
            return plan
        if u < p_sack + p_scr:
            plan.scramble = True
            return plan
        throwaway = rng.random() < br["throwaway"] * (0.3 if call.family == "screen" else 1.0)

        # 3) 실제 던진 깊이
        weights = {}
        intent = call.intent or call.family
        for depth, w in self.intent[intent].items():
            k = self.depth_ratio_power  # 의도가 일부만 바뀔 수 있어 희석되는 커버리지 효과를 실측 크기로 맞춘다
            weights[depth] = (w * T.tables()["depth_ratio_cov"][call.coverage][depth] ** k
                              * T.tables()["depth_ratio_pressure"][str(pressure)][depth] ** k)
        depth = T.choose(weights, rng.random())
        plan.extra["depth"] = depth

        # 4) 타깃·수비수
        cands = [p for pos in ("WR", "TE", "RB") for p in (g.playersOnField[o].get(pos) or [])]
        pos_w = TARGET_POS_WEIGHT[depth]
        target = rng.choice(cands, lambda p: pos_w.get(p.pos, 0.1) * math.exp(0.6 * A.mix(p, A.REC_BY_DEPTH[depth], N)))
        cov_players = self._on(g, d, "CB", "S", "LB")
        cov_w = A.MAN if call.coverage in A.MAN_COVERAGES else A.ZONE
        defender = rng.choice(cov_players, lambda p: math.exp(0.4 * A.mix(p, cov_w, N))
                              * (1.5 if p.pos == "CB" else 1.0 if p.pos == "S" else 0.5)) if cov_players else None

        qb_s = A.mix(qb, A.QB_BY_DEPTH[depth], N)
        rec_s = A.mix(target, A.REC_BY_DEPTH[depth], N)
        def_s = 0.6 * A.mix(defender, cov_w, N) + 0.4 * A.unit(cov_players, cov_w, N, 0.0) if defender else 0.0
        d_pass = qb_s + (rec_s - def_s) - c.get("pass", 0.0)
        d_int = A.z(qb, "decision", N) - (A.z(defender, "ball_skills", N) if defender else 0.0) - c.get("int", 0.0)
        tacklers = self._on(g, d, "LB", "S", "CB")
        d_yac = A.mix(target, A.YAC, N) - A.unit(tacklers, A.TACKLE, N, 0.0) - c.get("yac", 0.0)
        home = self._home(g)

        zone2 = "red" if call.zone in ("red", "goal") else "open"
        pa = int(call.play_action)
        rates = T.lookup("pass_rates", depth, pressure, zone2, pa, call.coverage)
        p_cmp = 0.0 if throwaway else T.logit_shift(rates["cmp"], self.beta["completion"] * d_pass + home)
        p_int = 0.0 if throwaway else T.logit_shift(max(rates["int"], 1e-4), -self.beta["interception"] * d_int)

        air = T.sample_quantile(T.lookup("pass_air", depth, zone2, pa, call.coverage), rng.random(),
                                self.beta["air"] * d_pass)
        r = rng.random()
        plan.target, plan.defender = target, defender
        plan.interception = r < p_int
        plan.complete = (not plan.interception) and r < p_int + p_cmp
        if plan.complete:
            yac = T.sample_quantile(T.lookup("pass_yac", depth, zone2, call.coverage), rng.random(),
                                    self.beta["yac"] * d_yac + home)
            plan.yds = round(air + yac)
        else:
            plan.yds = round(air)
        plan.extra.update({"throwaway": throwaway, "d_pass": round(d_pass, 3), "d_rush": round(d_rush, 3),
                           "d_int": round(d_int, 3), "d_yac": round(d_yac, 3), "pocket": round(qb_pocket, 3),
                           "mobility": round(qb_move, 3)})
        return plan

    # ── 런 ────────────────────────────────────────────────
    def run_play(self, g: "GameSim", positions: list[str], scramble: bool) -> RunPlan:
        rng, o, d = g.rng, g.o, g.d
        N = g.norms
        home = self._home(g)
        yl = 100 - g.scrimmage
        tacklers = self._on(g, d, "LB", "S", "CB")
        if scramble:
            qb = g.getTopPlayerOnField(o, "QB")
            zone2 = "red" if yl <= 20 else "open"
            d_scr = A.mix(qb, A.MOBILITY, N) - A.unit(tacklers, A.TACKLE, N, 0.0) - self.center.get("scramble", 0.0)
            yds = round(T.sample_quantile(T.lookup("scramble_yards", zone2), rng.random(),
                                          self.beta["scramble_yards"] * d_scr + home))
            return RunPlan(carrier=qb, rbw=None, yds=yds, extra={"family": "scramble", "d_scr": round(d_scr, 3)})

        call: Call = g.call or self.call_play(g, "run")
        family = call.family
        rbs = g.playersOnField[o].get("RB") or []
        qb = g.getTopPlayerOnField(o, "QB")
        if family == "sneak" or not rbs:
            carrier = qb
        else:
            u = rng.random()
            qb_run_rate = 0.02 + max(0.0, A.z(qb, "speed", N) * 0.02)
            wrs = g.playersOnField[o].get("WR") or []
            if u < qb_run_rate:
                carrier = qb
            elif u < qb_run_rate + 0.03 and wrs:
                carrier = rng.choice(wrs, lambda p: A.a(p, "speed"))
            else:
                carrier = rbs[0] if (len(rbs) == 1 or rng.random() < 0.8) else rng.choice(rbs[1:])

        blockers = self._on(g, o, "OL") + self._on(g, o, "TE")[:1]
        front = self._on(g, d, "DL", "LB")
        d_line = A.unit(blockers, A.RUN_BLOCK, N) - A.unit(front, A.RUN_DEF, N, 0.2)
        d_carry = A.mix(carrier, A.CARRY, N) - A.unit(tacklers + front, A.TACKLE, N, 0.0)
        d_run = 0.6 * d_line + 0.4 * d_carry - self.center.get("run", 0.0)
        dd2 = "short" if call.dd.endswith("s") else "std"
        table = T.lookup("run", family, call.zone, call.box, dd2)
        yds = round(T.sample_quantile(table["q"], rng.random(), self.beta["run"] * d_run + home))
        rbw = {}
        for p in self._on(g, o, "OL"):
            rbw[p] = {"type": "OL", "won": rng.random() < 0.5 + 0.12 * d_line + (0.1 if yds > 3 else -0.1)}
        return RunPlan(carrier=carrier, rbw=rbw, yds=yds,
                       extra={"family": family, "box": call.box, "pers": call.personnel, "d_run": round(d_run, 3)})

    # ── 부가 ──────────────────────────────────────────────
    def prob_fumble(self, g: "GameSim", p: "PlayerGameSim") -> float:
        return self.fumble_per_touch * math.exp(-0.15 * A.z(p, "ball_security", g.norms)) * g.settings.fumble_factor

    def prob_made_field_goal(self, g: "GameSim", kicker: "PlayerGameSim") -> float:
        distance = 100 - g.scrimmage + 17
        indoor = (g.venue.get("roof") or "") in ("dome", "closed")
        base = D.fg_base_prob(distance, indoor)  # 실측 표. 임시 모델용 fg_accuracy_factor는 쓰지 않는다
        if base <= 0.0:
            return 0.0
        power = max(0.0, distance - 45) / 10 * A.z(kicker, "kick_power", g.norms) * 0.3
        shift = self.beta["kick"] * A.z(kicker, "kick_accuracy", g.norms) * 2 + power
        return T.logit_shift(min(base, 0.999), shift)

    def kickoff(self, g: "GameSim", kicker: "PlayerGameSim", returner: "PlayerGameSim") -> tuple[int, bool, int]:
        rows = T.tables()["special"]["kickoff_rows"]
        kick_to, touchback, ret = rows[int(g.rng.random() * len(rows))]
        if not touchback:
            ret = round(ret + self.beta["returns"] * A.z(returner, "returning", g.norms) * 8)
        return kick_to, bool(touchback), ret

    def kickoff_return_yds(self, g: "GameSim", returner: "PlayerGameSim") -> int:  # 안전 킥 등 예외 경로
        return round(g.rng.trunc_gauss(20, 8, -5, 60))

    def punt_distance(self, g: "GameSim", punter: "PlayerGameSim") -> int:
        yl = 100 - g.scrimmage
        rows = T.tables()["special"]["punt_rows"][D.punt_bucket(yl)]
        row = rows[int(g.rng.random() * len(rows))]
        self._punt_row = row
        power = A.z(punter, "punt_power", g.norms) * 1.5
        return max(20, round(row[0] + power))

    def punt_return_yds(self, g: "GameSim", returner: "PlayerGameSim") -> int:
        ret = self._punt_row[2] if self._punt_row else 0
        if ret > 0:
            ret = round(ret + self.beta["returns"] * A.z(returner, "returning", g.norms) * 5)
        return ret

    # ── 판단 ──────────────────────────────────────────────
    def fourth_down_decision(self, g: "GameSim") -> str:
        kicker = next((p for p in g.team[g.o].depth.get("K", []) if not p.injured), None)
        p_make = self.prob_made_field_goal(g, kicker) if kicker is not None else 0.0
        return D.fourth_down_choice(g, p_make)

    def two_point_decision(self, g: "GameSim") -> bool:
        sp = T.tables()["special"]
        return D.two_point_choice(g, sp["xp_rate"], sp["two_point_rate"])

    def xp_prob(self, g: "GameSim", kicker: "PlayerGameSim") -> float:
        return T.logit_shift(T.tables()["special"]["xp_rate"], self.beta["kick"] * 2 * A.z(kicker, "kick_accuracy", g.norms))

    def win_probability(self, g: "GameSim") -> float:
        return D.home_win_probability(g)

    def state_values(self, g: "GameSim") -> dict:
        yl = 100 - g.scrimmage
        ep = D.M.ep(g.down, g.toGo, yl) if 0 < yl < 100 and g.awaitingKickoff is None and not g.awaitingAfterTouchdown else None
        return {"ep": None if ep is None else round(ep, 3), "home_wp": round(D.home_win_probability(g), 4)}
