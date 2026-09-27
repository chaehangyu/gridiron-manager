"""Football GM 원본 결과 공식 (임시 결과 모델).

원본 index.ts의 probPass, doPass/doRun 수치 부분, probSack, probInt, probComplete, probScramble,
probFumble, probMadeFieldGoal, 킥·펀트 리턴 공식을 그대로 옮겼다.
M2에서 실측 기준 분포 기반 모델(ENGINE_DESIGN §5)로 교체한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..skeleton.rng import bound
from .base import PassPlan, RunPlan

if TYPE_CHECKING:
    from ..skeleton.game import GameSim
    from ..skeleton.types import PlayerGameSim

AVERAGE_TACKLING_COMPOSITE = 0.56
FIELD_GOAL_DISTANCE_ADDED = 17

# (거리 상한, 기본 성공률) — 원본 probMadeFieldGoal 표
_FG_TABLE = [
    (20, 0.99), (30, 0.98), (35, 0.95), (37, 0.94), (38, 0.93), (39, 0.92), (40, 0.91), (41, 0.89),
    (42, 0.87), (43, 0.85), (44, 0.83), (45, 0.81), (46, 0.79), (47, 0.77), (48, 0.75), (49, 0.73),
    (50, 0.71), (51, 0.69), (52, 0.65), (53, 0.61), (54, 0.59), (55, 0.55), (56, 0.51), (57, 0.47),
    (58, 0.43), (59, 0.39), (60, 0.35), (61, 0.3), (62, 0.25), (63, 0.2), (64, 0.1), (65, 0.05),
    (70, 0.005), (75, 0.0001), (80, 0.000001),
]


class FbgmOutcome:
    name = "fbgm"

    # ── 플레이 선택 ───────────────────────────────────────
    def prob_pass(self, g: "GameSim") -> float:
        s = g.settings
        g.updatePlayersOnField("startersFake")
        pts_down = g.team[g.d].stat["pts"] - g.team[g.o].stat["pts"]
        quarter = len(g.team[0].stat["ptsQtrs"])
        desperation = g.scrimmage < 97 and quarter >= g.num_periods and (
            (quarter > g.num_periods and pts_down > 0)
            or (pts_down > 0 and g.clock <= 2)
            or (pts_down > 8 and g.clock <= 3)
            or (pts_down > 16 and g.clock <= 4)
            or (pts_down > 24 and g.clock <= 6)
        )
        if desperation:
            return 0.98 * s.pass_factor

        oc, dc = g.team[g.o].composite, g.team[g.d].composite
        off_passing = 0.0
        if g.playersOnField[g.o].get("QB"):
            qb = g.getTopPlayerOnField(g.o, "QB")
            off_passing = (5 * qb.ovrs["QB"] / 100 + oc["receiving"] + oc["passBlocking"]) / 7
        off_rushing = (oc["rushing"] + oc["runBlocking"]) / 2
        def_passing = (dc["passRushing"] + dc["passCoverage"]) / 2
        def_rushing = dc["runStopping"]

        off_passing = bound((off_passing - 0.45) * (0.5 / 0.25) + 0.25, 0, 1)
        off_rushing = bound((off_rushing - 0.5) * (0.5 / 0.2) + 0.25, 0, 1)
        def_passing = bound((def_passing - 0.4) * (0.5 / 0.25) + 0.25, 0, 1)
        def_rushing = bound((def_rushing - 0.4) * (0.5 / 0.2) + 0.25, 0, 1)

        passing_tendency = 1.075 * bound(off_passing - 0.25 * def_passing, 0, 1)
        rushing_tendency = 0.925 * bound(off_rushing - 0.25 * def_rushing, 0, 1)
        pass_odds = 0.57
        if passing_tendency > 0 or rushing_tendency > 0:
            pass_odds = bound((1.5 * passing_tendency) / (1.5 * passing_tendency + rushing_tendency), 0.45, 0.65)
        if g.scrimmage >= 95:
            pass_odds = pass_odds / (g.scrimmage - 94)
        return pass_odds * s.pass_factor

    # ── 패스 ──────────────────────────────────────────────
    def _block_attempts(self, g: "GameSim", rating: str, versus: str, scale: float, base: float,
                        te_prob: float, te_base: float, rb_prob: float, rb_base: float,
                        exclude: "PlayerGameSim | None" = None) -> dict:
        o, d = g.o, g.d
        rng = g.rng
        out: dict = {}

        def attempt(p: "PlayerGameSim", kind: str, baseline: float) -> None:
            ratio = p.composite[rating] / g.team[d].composite[versus]
            prob_win = bound((ratio - baseline) * (scale / 0.25) + base, 0, 0.96)
            out[p] = {"type": kind, "won": rng.random() < prob_win}

        for p in g.playersOnField[o].get("OL", []) or []:
            attempt(p, "OL", 1)
        for p in g.playersOnField[o].get("TE", []) or []:
            if p is not exclude and rng.random() < te_prob:
                attempt(p, "Other", te_base)
        for p in g.playersOnField[o].get("RB", []) or []:
            if p is not exclude and rng.random() < rb_prob:
                attempt(p, "Other", rb_base)
        return out

    def prob_sack(self, g: "GameSim", qb: "PlayerGameSim") -> float:
        return (0.06 * g.team[g.d].composite["passRushing"]) / (
            0.5 * (qb.composite["avoidingSacks"] + g.team[g.o].composite["passBlocking"])
        ) * g.settings.sack_factor

    def prob_int(self, g: "GameSim", qb: "PlayerGameSim", defender: "PlayerGameSim") -> float:
        dc, oc = g.team[g.d].composite, g.team[g.o].composite
        return ((((0.004 * dc["passCoverage"] + 0.022 * defender.composite["passCoverage"])
                  / (0.5 * (qb.composite["passingVision"] + qb.composite["passingAccuracy"])))
                 * dc["passRushing"]) / oc["passBlocking"]) * g.settings.int_factor

    def prob_complete(self, g: "GameSim", qb: "PlayerGameSim", target: "PlayerGameSim",
                      defender: "PlayerGameSim") -> float:
        dc, oc = g.team[g.d].composite, g.team[g.o].composite
        factor = ((0.2 * (target.composite["catching"] + target.composite["gettingOpen"]
                          + qb.composite["passingAccuracy"] + qb.composite["passingDeep"]
                          + qb.composite["passingVision"]))
                  / (0.5 * (defender.composite["passCoverage"] + dc["passCoverage"]))) * (
            (oc["passBlocking"] / dc["passRushing"]) ** 0.5)
        return bound((0.19 + 0.4 * factor ** 1.25) * g.settings.completion_factor, 0, 0.95)

    def prob_scramble(self, g: "GameSim", qb: "PlayerGameSim | None") -> float:
        qb_rb = qb.ovrs["RB"] if qb is not None else 0
        return (0.01 + max(0.0, (0.35 * (qb_rb - 30)) / 100)) * g.settings.scramble_factor

    def pass_play(self, g: "GameSim") -> PassPlan:
        rng, o, d = g.rng, g.o, g.d
        plan = PassPlan()
        plan.pbw = self._block_attempts(g, "passBlocking", "passRushing", 0.45, 0.5, 0.1, 0.75, 0.5, 0.5)
        qb = g.getTopPlayerOnField(o, "QB")
        if rng.random() < 0.75 and rng.random() < g.probFumble(qb):
            plan.qb_fumble = True
            plan.qb_fumble_yds = rng.rand_int(-1, -10)
            return plan
        if rng.random() < self.prob_sack(g, qb):
            plan.sack = True
            return plan
        qbs = g.playersOnField[o].get("QB")
        if self.prob_scramble(g, qbs[0] if qbs else None) > rng.random():
            plan.scramble = True
            return plan

        target = g.pickPlayer(o, "catching" if rng.random() < 0.2 else "gettingOpen", ["WR", "TE", "RB"], 1.5)
        rb_factor = target.composite["gettingOpen"] if (
            target in (g.playersOnField[o].get("RB") or []) and rng.random() < 0.75) else 1
        mean = bound(rb_factor * 8.6 * (g.team[o].composite["passBlocking"] / g.team[d].composite["passRushing"]), -5, 100)
        yds = js_round(rng.trunc_gauss(mean, rb_factor * 7, -5, 100))
        if rng.random() < qb.composite["passingDeep"] * 0.05:
            yds += rng.rand_int(0, 109)
        yds += js_round((target.composite["speed"] - 0.5) * 6)
        if rng.random() < target.composite["speed"] * 0.025:
            yds += rng.rand_int(0, 109)
        if yds < 0:
            yds += rng.rand_int(0, 5)
        yds = js_round(yds * g.settings.pass_yds_factor)

        defender = g.pickPlayer(d, "passCoverage", None, 2)
        plan.target = target
        plan.defender = defender
        plan.yds = yds
        plan.complete = rng.random() < self.prob_complete(g, qb, target, defender)
        plan.interception = rng.random() < self.prob_int(g, qb, defender)
        return plan

    # ── 런 ────────────────────────────────────────────────
    def run_play(self, g: "GameSim", positions: list[str], scramble: bool) -> RunPlan:
        rng, o, d = g.rng, g.o, g.d
        p = g.pickPlayer(o, "rushing", positions)
        rbw = None
        if not scramble:
            rbw = self._block_attempts(g, "runBlocking", "runStopping", 0.65, 0.3, 0.75, 0.85, 0.25, 0.6, exclude=p)
        modifier = 3 if scramble else 1
        mean = bound((modifier * (3.5 * 0.5 * (p.composite["rushing"] + g.team[o].composite["runBlocking"])))
                     / g.team[d].composite["runStopping"], -5, 15)
        yds = js_round(rng.trunc_gauss(mean, 6, -5, 15))
        if rng.random() < 0.01:
            yds += rng.rand_int(0, 109)
        if yds < 0:
            yds += rng.rand_int(0, 5)
        yds = js_round(yds * g.settings.rush_yds_factor)
        return RunPlan(carrier=p, rbw=rbw, yds=yds)

    # ── 공통 ──────────────────────────────────────────────
    def prob_fumble(self, g: "GameSim", p: "PlayerGameSim") -> float:
        cur = g.currentPlay.state["current"]
        o, d = cur.o, cur.d
        pof = g.playersOnField[o]
        offense_has_ball = pof.get("QB") or pof.get("RB") or pof.get("P") or pof.get("K")
        if not offense_has_ball:
            tackling_factor = 0.5
        else:
            tackling_factor = (g.team[d].composite["tackling"] / AVERAGE_TACKLING_COMPOSITE) ** 2
        return 0.0125 * (1.5 - p.composite["ballSecurity"]) * g.settings.fumble_factor * tackling_factor

    def prob_made_field_goal(self, g: "GameSim", kicker: "PlayerGameSim") -> float:
        distance = 100 - g.scrimmage + FIELD_GOAL_DISTANCE_ADDED
        distance += -(kicker.composite["kickingPower"] - 0.75) * 20
        base = 0.0
        for limit, prob in _FG_TABLE:
            if distance < limit:
                base = prob
                break
        base = min(0.99, base * g.settings.fg_accuracy_factor)
        base_boost = (kicker.composite["kickingAccuracy"] - 0.7) / 3
        return base + min(base_boost, (1 - base) / 2, base / 2)

    def kickoff_return_yds(self, g: "GameSim", returner: "PlayerGameSim") -> int:
        mean = 15 + 10 * returner.composite["rushing"]
        yds = js_round(g.rng.trunc_gauss(mean, 5, -10, 109))
        if g.rng.random() < returner.composite["speed"] ** 3 * 0.025:
            yds += g.rng.rand_int(0, 109)
        return yds

    def punt_distance(self, g: "GameSim", punter: "PlayerGameSim") -> int:
        adjustment = (punter.composite["puntingPower"] - 0.7) * 20
        distance = js_round(g.rng.trunc_gauss(50 + adjustment, 8, 25, 90))
        if g.scrimmage + distance >= 100 and g.rng.random() < punter.composite["puntingAccuracy"] ** 1.5 * 0.95:
            target = g.rng.rand_int(99, max(81, g.scrimmage))
            distance = target - g.scrimmage
        return distance

    def punt_return_yds(self, g: "GameSim", returner: "PlayerGameSim") -> int:
        mean = 4 + 10 * returner.composite["rushing"]
        yds = js_round(g.rng.trunc_gauss(mean, 10, -10, 109))
        if g.rng.random() < returner.composite["speed"] ** 3 * 0.06:
            yds += g.rng.rand_int(0, 109)
        return yds


def js_round(x: float) -> int:
    import math
    return math.floor(x + 0.5)
