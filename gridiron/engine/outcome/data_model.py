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
from ...tactics import familiarity as F
from ...tactics.model import MAN_COVERS
from .. import adjust as A
from ..ai import coordinator as C
from ..ai import decisions as D
from . import context as CX
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
    scheme: str = "zone"          # 런 블로킹 스킴: zone | gap
    b_pass: float = 0.5           # 콜 직전 수비 믿음 (패스일 확률)
    neutral: float = 0.5          # 리그 중립 패스 확률 (퍼스넬 반영)
    anticip: float = 0.0          # 읽힘 효과 (Δ 단위, ≤ 0)
    obvious: float = 0.0          # 뻔한 패스 상황 압박 로짓 가산
    drill: float = 0.0            # 상황 훈련 보너스 (공격 − 수비, 이동 단위)
    countered: bool = False       # 수비 콜이 이 플레이에 유리했나 (상대 적중률)
    xp: float = 0.5               # 리그 기대 패스 확률 (퍼스넬 반영 전)
    gs: str = "close"             # 점수·시간 상황 (close | lead | trail | two_min)
    fz: str = "opp"               # 필드 구역 (backed | own | opp | red | goal)


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


RUN_STYLE_FAMILY = {"mixed": {}, "inside_zone": {"inside": 1.3}, "outside_zone": {"outside": 1.6},
                    "gap": {"inside": 1.5}}
RUN_STYLE_ZONE = {"mixed": 0.5, "inside_zone": 0.85, "outside_zone": 0.9, "gap": 0.15}
BOX_ORDER = ["light", "normal", "heavy"]


class DataOutcome:
    name = "data"

    def __init__(self, beta_scale: float | None = None, center: dict[str, float] | None = None,
                 explain: bool = False, learning: bool = True, situation_shift: dict | None = None) -> None:
        """beta_scale·center는 보정 도구(재현 테스트·중심 측정)가 설정 파일 값을 바꿔 볼 때만 넘긴다.

        explain: 플레이마다 결과 이동 기여분(능력치·숙련도·읽힘·훈련·홈)을 분해해 기록 (ENGINE_DESIGN §8, T8).
        learning: False면 경기 중 믿음·대응·읽힘을 끈다 (대조군, T4).
        """
        p = _params()
        scale = p.get("beta_scale", 1.0) if beta_scale is None else beta_scale
        self.beta = {k: v * scale for k, v in p["beta"].items()}
        self.home_adv = p["home_advantage"]
        self.fumble_per_touch = p["fumble_per_touch"]
        self.intent = p["intent_to_depth"]
        self.center = dict(p.get("center", {})) if center is None else center
        self.depth_ratio_power = p.get("depth_ratio_power", 1.0)
        self.cp = p["coordinator"]
        # 다운·거리 구간별 패스 결과 보정 (tools/calibrate_situations.py로 적합, M4 구현 노트)
        ss = (p.get("situation_shift") or {}) if situation_shift is None else situation_shift
        self.situ_shift = dict(ss.get("pass", {}))       # 다운·거리 구간별 (패스)
        self.situ_gs = dict(ss.get("pass_gs", {}))       # 점수·시간 상황별 (패스)
        self.situ_run = dict(ss.get("run", {}))          # 다운·거리 구간별 (런)
        self.situ_fz = dict(ss.get("pass_fz", {}))       # 필드 구역별 (패스; 상대 진영 기준 0)
        self.explain = explain
        self.learning = learning
        self._punt_row = None
        self._game = None
        self.sides: list[CX.Side] = []
        self._cache: dict = {}

    @classmethod
    def for_league(cls, league, **kw) -> "DataOutcome":
        """리그 능력치 분포에 맞는 중심값을 쓴다: 실측 능력치 리그는 `center`, 가상 샘플 리그는 `center_sample`."""
        p = _params()
        if getattr(league, "source", "") == "sample" and "center_sample" in p:
            return cls(center=dict(p["center_sample"]), **kw)
        return cls(**kw)

    # ── 공통 ──────────────────────────────────────────────
    def _ctx(self, g: "GameSim") -> list["CX.Side"]:
        if self._game is not g:
            self._game = g
            self.sides = CX.build(g, self.center)
            self._cache = {}
        return self.sides

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

    def _choose(self, g: "GameSim", dist: dict) -> object:
        return T.choose(dist, g.rng.random())

    def _neutral_xpass(self, g: "GameSim") -> float:
        pts_down = g.team[g.d].stat["pts"] - g.team[g.o].stat["pts"]
        game_sec, half_sec = D.clock_state(g)
        yl = 100 - g.scrimmage
        wp = D.wp_for(g, g.o, -pts_down, g.down, g.toGo, yl)
        return D.M.xpass(g.down, g.toGo, yl, -pts_down, game_sec, half_sec, wp)

    def _buckets(self, g: "GameSim") -> tuple[str, str, str]:
        yl = 100 - g.scrimmage
        half_sec, second = C.half_info(g)
        self._half_sec = half_sec
        diff = g.team[g.o].stat["pts"] - g.team[g.d].stat["pts"]
        return C.dd8(g.down, g.toGo), C.field5(yl), C.game_state(diff, half_sec, second)

    # ── 플레이 선택 ───────────────────────────────────────
    def prob_pass(self, g: "GameSim") -> float:
        pts_down = g.team[g.d].stat["pts"] - g.team[g.o].stat["pts"]
        quarter = len(g.team[0].stat["ptsQtrs"])
        if g.scrimmage < 97 and quarter >= g.num_periods and (
            (quarter > g.num_periods and pts_down > 0) or (pts_down > 0 and g.clock <= 2)
            or (pts_down > 8 and g.clock <= 3) or (pts_down > 16 and g.clock <= 4) or (pts_down > 24 and g.clock <= 6)
        ):
            return 0.98 * g.settings.pass_factor
        xp = self._neutral_xpass(g)
        off, dfn = self._ctx(g)[g.o], self._ctx(g)[g.d]
        dd, fz, gs = self._buckets(g)
        tac = off.tactics
        shift = tac.offense.pass_shift()
        situ = C.situational(tac, dd, fz)
        if "pass" in situ:
            shift += C.logit(min(0.97, max(0.03, xp + situ["pass"]))) - C.logit(xp)
        if self.learning:
            # 성향 깨기: 상대가 가진 우리 믿음의 편차를 우리도 셀프 스카우팅으로 안다 (§6.6)
            dev = dfn.knows_opp_off.dev(C.OffenseBelief.keys(dd, fz, gs, "*"))
            shift += C.tendency_break(tac.predictability.tendency_break, dev)
            # 상대가 박스를 무겁게 쓰면 패스를 조금 늘린다 (§6.4 공격 쪽 대응)
            shift += off.lam * self.cp["kind_box_k"] * off.knows_opp_def.box_tilt()
        return C.sigmoid(C.logit(xp) + shift) * g.settings.pass_factor

    def call_play(self, g: "GameSim", kind: str) -> Call:
        rng = g.rng
        yl = 100 - g.scrimmage
        dd_tab, zone = dd_class(g.down, g.toGo), zone_of(yl)
        sides = self._ctx(g)
        off, dfn = sides[g.o], sides[g.d]
        dd, fz, gs = self._buckets(g)
        xp = self._neutral_xpass(g)
        otac, dtac = off.tactics, dfn.tactics
        cp = self.cp

        # 퍼스넬: 실측 분포 × 전술 배율 (퍼스넬 섞기면 런·패스와 무관하게 고른다)
        if otac.predictability.personnel_mix:
            pp, pr = T.lookup("personnel", "pass", dd_tab), T.lookup("personnel", "run", dd_tab)
            base = {k: xp * pp.get(k, 0.0) + (1 - xp) * pr.get(k, 0.0) for k in set(pp) | set(pr)}
        else:
            base = T.lookup("personnel", kind, dd_tab)
        pm = otac.offense.personnel
        pers = self._choose(g, {k: v * pm.get(k, 1.0) for k, v in base.items()})
        front = getattr(g.team[g.d], "front", "4-3")
        dpers = self._choose(g, T.lookup("def_personnel", pers))

        keys = C.OffenseBelief.keys(dd, fz, gs, pers)
        neutral = C.neutral_pass(xp, dd_tab, pers)
        b_pass = dfn.knows_opp_off.b_pass(keys, neutral) if self.learning else neutral
        lam_d = dfn.lam if self.learning else 0.0
        lam_o = off.lam if self.learning else 0.0

        # ── 수비 콜 (커버리지 × 블리츠) ──
        dsitu = C.situational(dtac, dd, fz)
        ck = (d_idx := g.d, dd_tab, pers, dd, fz)
        if ck not in self._cache:
            B = C.identity_coverage(dd_tab, pers, dtac, dsitu)
            fam0_ = self._intent_mix(dd_tab, zone)
            fit = {c: cp["fit_cov"] * dfn.fit_def["man" if c[0] in MAN_COVERS else "zone"]
                   + cp["fit_blitz"] * dfn.fit_def["blitz"] * c[1] for c in B}
            v0 = {c: C.pass_value(fam0_, c) for c in B}
            self._cache[ck] = (B, fam0_, fit, v0)
        B_D, fam0, fit_d, v0 = self._cache[ck]
        _ = d_idx
        b_fam = dfn.knows_opp_off.fam_probs(dd, fam0) if self.learning else fam0
        if self.learning:
            gain_d = {c: -(b_pass * C.pass_value(b_fam, c) - neutral * v0[c]) + fit_d[c] for c in B_D}
        else:
            gain_d = {c: -(b_pass - neutral) * v0[c] + fit_d[c] for c in B_D}
        # λ=0(학습 끔·사용자가 대응 0)이어도 우리 로스터 궁합에 맞춘 콜 조정은 fit_floor 강도로 남는다
        pi_d = C.tilt(B_D, gain_d, max(lam_d, cp["fit_floor"]), dfn.tau)
        cov, blitz = self._choose(g, pi_d)

        # ── 공격 패밀리 ──
        o = otac.offense
        scheme = "zone"
        if kind == "pass":
            mix = self._intent_mix(dd_tab, zone)
            mult = {"screen": o.screen, "quick": o.short, "inter": o.mid, "deep": o.deep}
            style = {"screen": -0.15, "quick": -0.2, "inter": 0.05, "deep": 0.3}
            B = {f: mix[f] * mult[f] * math.exp(style[f] * o.qb_style) for f in mix}
            lk = ("lc", dd_tab, pers)
            if lk not in self._cache:
                lc_, lcalls_, lblitz_ = C.league_coverage(dd_tab, pers)
                self._cache[lk] = (lc_, lcalls_, lblitz_, {f: C.family_value(f, lcalls_) for f in C.PASS_FAMS})
            lc, lcalls, lblitz, fv0 = self._cache[lk]
            if self.learning:
                calls_b = off.knows_opp_def.calls(dd, lc, lblitz)
                gain = {f: C.family_value(f, calls_b) - fv0[f] + cp["fit_off"] * off.fit_off[f] for f in B}
            else:
                gain = {f: cp["fit_off"] * off.fit_off[f] for f in B}
            family = self._choose(g, C.tilt(B, gain, max(lam_o, cp["fit_floor"]), off.tau))
            intent = family
            pa = family != "screen" and rng.random() < min(0.8, T.lookup("pa_rate", dd_tab, zone) * o.play_action)
        else:
            fams = dict(T.lookup("run_family", dd_tab, zone))
            for f, m in RUN_STYLE_FAMILY[o.run_style].items():
                if f in fams:
                    fams[f] *= m
            if self.learning:
                lbox = T.lookup("box", "run", dd_tab, pers, 0)
                tilt_b = off.knows_opp_def.box_tilt()
                bbox = {"light": max(0.01, lbox.get("light", 0) - tilt_b / 2), "normal": lbox.get("normal", 0),
                        "heavy": max(0.01, lbox.get("heavy", 0) + tilt_b / 2)}
                gain = {f: (C.run_value(f, bbox) - C.run_value(f, lbox)) if f in C.RUN_FAMS else 0.0 for f in fams}
                fams = C.tilt(fams, gain, lam_o, off.tau)
            family = self._choose(g, fams)
            if family == "sneak" and g.toGo > 2:
                family = "inside"
            pa = False
            intent = None
            scheme = "zone" if rng.random() < RUN_STYLE_ZONE[o.run_style] else "gap"

        # ── 박스: 실측(실제 종류 조건) + 전술 성향 + 믿음 ──
        box_dist = T.lookup("box", kind, dd_tab, pers, blitz)
        box = self._choose(g, box_dist)
        lean = 0.6 * dtac.defense.box + lam_d * cp["box_k"] * ((1 - b_pass) - (1 - neutral))
        i = BOX_ORDER.index(box)
        if lean > 0 and i < 2 and rng.random() < min(0.6, lean):
            box = BOX_ORDER[i + 1]
        elif lean < 0 and i > 0 and rng.random() < min(0.6, -lean):
            box = BOX_ORDER[i - 1]

        # ── 읽힘 효과 (경로 ②) ──
        anticip, obvious = 0.0, 0.0
        if self.learning:
            # 읽힘 효과는 리그 중립보다 문턱(read_threshold) 넘게 치우친 만큼만 (실제 팀 성향 범위 ±0.1 안은 거의 0)
            thr = cp["read_threshold"]
            if kind == "pass":
                anticip = -cp["gamma_pass"] * max(0.0, b_pass - neutral - thr)
                if dd_tab in ("2l", "3m", "3l", "4m", "4l"):
                    obvious = cp["delta_obvious"] * max(0.0, b_pass - max(0.8, neutral))
            else:
                anticip = -cp["gamma_run"] * max(0.0, (1 - b_pass) - (1 - neutral) - thr)

        # ── 상황 훈련 보너스 ──
        half_sec = self._half_sec
        situ_tags = [k for k, ok in (("redzone", yl <= 20), ("third_down", g.down >= 3), ("two_minute", half_sec <= 120)) if ok]
        drill = sum(off.prep.get("drill", {}).get(k, 0.0) for k in situ_tags) \
            - sum(dfn.prep.get("drill", {}).get(k, 0.0) for k in situ_tags)

        # ── 관측·기록 ──
        countered = False
        if kind == "pass":
            po = C.payoff()["pass"][family]
            avg = sum(p * po[c][str(b)] for (c, b), p in B_D.items())
            countered = po[cov][str(blitz)] < avg
        else:
            countered = box == "heavy"
        if self.learning:
            dfn.knows_opp_off.observe(keys, kind == "pass", neutral, family if kind == "pass" else None)
            off.knows_opp_def.observe(dd, cov, blitz, box, box_dist)
        so, sd = off.summary["off"], dfn.summary["def"]
        so["plays"] += 1
        so["pass"] += kind == "pass"
        so["xpass"] += xp
        so["fam"][family] = so["fam"].get(family, 0.0) + 1
        so["pa"] += bool(pa)
        if kind == "pass":
            sd["pass_faced"] += 1
            sd["cov"][cov] = sd["cov"].get(cov, 0.0) + 1
            sd["blitz"] += blitz
            off.add_usage("pass_total")
            off.add_usage("pass_" + family)
            if pa:
                off.add_usage("pass_pa")
            dfn.add_usage("cov_man" if cov in MAN_COVERS else "cov_zone")
            dfn.add_usage("def_pass_total")
            dfn.add_usage("blitz", blitz)
        else:
            sd["runs_faced"] += 1
            off.add_usage("run_" + scheme)
        sd["box"][box] = sd["box"].get(box, 0.0) + 1
        dfn.add_usage("front_43" if front == "4-3" else "front_34")
        off.report["off_plays"] += 1
        off.report["countered"] += countered
        if anticip < 0:
            off.report["anticip"] += anticip
            off.report["anticip_plays"] += 1

        formation = {"off": OFF_FORMATIONS[pers], "def": DEF_FORMATIONS[(front, dpers)]}
        return Call(kind, pers, dpers, family, pa, cov, blitz, box, dd_tab, zone, formation, intent, scheme,
                    b_pass, neutral, anticip, obvious, drill, countered, xp, gs, fz)

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
        sides = self._ctx(g)
        off, dfn = sides[o], sides[d]
        qb = g.getTopPlayerOnField(o, "QB")
        plan = PassPlan(extra={"call": call.family, "pa": call.play_action, "cov": call.coverage,
                               "blitz": call.blitz, "pers": call.personnel, "box": call.box,
                               "b_pass": round(call.b_pass, 3), "xp": round(call.xp, 3), "dd": call.dd, "gs": call.gs})

        if rng.random() < 0.75 and rng.random() < g.probFumble(qb) * 0.5:
            plan.qb_fumble = True
            plan.qb_fumble_yds = rng.rand_int(-1, -10)
            return plan

        # 숙련도 배율 (콜이 속한 영역)
        intent = call.intent or call.family
        m_off = off.m("pass_" + intent)
        if call.play_action:
            m_off = math.sqrt(m_off * off.m("pass_pa"))
        cov_type = "man" if call.coverage in MAN_COVERS else "zone"
        m_cov = dfn.m("cov_" + cov_type)
        front = getattr(g.team[d], "front", "4-3")
        m_rush = dfn.m("front_43" if front == "4-3" else "front_34")
        if call.blitz:
            m_rush = math.sqrt(m_rush * dfn.m("blitz"))

        # 1) 압박
        blockers = self._on(g, o, "OL")
        rush_w = A.scheme("pass_rush", front)
        c = self.center

        def rush_score(m: float) -> float:
            vals = [A.mix(p, rush_w, N, m) for p in self._on(g, d, "DL")]
            if call.blitz:
                vals += [A.mix(p, A.scheme("blitz_rush"), N, m) for p in self._on(g, d, "LB", "S")[:1]]
            if not vals:
                return -2.0
            vals.sort(reverse=True)
            top = vals[:4 + call.blitz]
            return sum(top) / len(top)

        pb_w = A.scheme("pass_block")
        d_rush = rush_score(m_rush) - A.unit(blockers, pb_w, N, m=m_off) - c.get("rush", 0.0)
        passing_down = 1 if call.dd in ("2l", "3m", "3l", "4m", "4l") else 0
        p_press = T.lookup("pressure", call.coverage, call.blitz, passing_down)
        p_press = T.logit_shift(p_press, self.beta["pressure"] * d_rush + call.obvious)
        pressure = 1 if rng.random() < p_press else 0
        plan.extra["pressure"] = pressure
        plan.pbw = {p: {"type": "OL", "won": True} for p in blockers}
        if pressure and blockers:
            loser = min(blockers, key=lambda p: A.mix(p, pb_w, N) + rng.random() * 1.5)
            plan.pbw[loser] = {"type": "OL", "won": False}

        # 2) 드롭백 분기
        br = T.lookup("dropback_branch", pressure, passing_down, call.blitz)
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
            self._scramble_extra = dict(plan.extra)
            return plan
        throwaway = rng.random() < br["throwaway"] * (0.3 if call.family == "screen" else 1.0)

        # 3) 실제 던진 깊이
        weights = {}
        for depth, w in self.intent[intent].items():
            k = self.depth_ratio_power  # 의도가 일부만 바뀔 수 있어 희석되는 커버리지 효과를 실측 크기로 맞춘다
            weights[depth] = (w * T.tables()["depth_ratio_cov"][call.coverage][depth] ** k
                              * T.tables()["depth_ratio_pressure"][str(pressure)][depth] ** k)
        depth = T.choose(weights, rng.random())
        plan.extra["depth"] = depth

        # 4) 타깃·수비수
        cands = [p for pos in ("WR", "TE", "RB") for p in (g.playersOnField[o].get(pos) or [])]
        pos_w = TARGET_POS_WEIGHT[depth]
        rec_w, qb_w = A.scheme("receiver", depth), A.scheme("qb", depth)
        target = rng.choice(cands, lambda p: pos_w.get(p.pos, 0.1) * math.exp(0.6 * A.mix(p, rec_w, N)))
        cov_players = self._on(g, d, "CB", "S", "LB")
        cov_w = A.scheme("coverage", cov_type)
        defender = rng.choice(cov_players, lambda p: math.exp(0.4 * A.mix(p, cov_w, N))
                              * (1.5 if p.pos == "CB" else 1.0 if p.pos == "S" else 0.5)) if cov_players else None

        def pass_delta(mo: float, md: float, weights_cov: dict) -> float:
            qb_s = A.mix(qb, qb_w, N, mo)
            rec_s = A.mix(target, rec_w, N, mo)
            def_s = (0.6 * A.mix(defender, weights_cov, N, md) + 0.4 * A.unit(cov_players, weights_cov, N, 0.0, md)
                     if defender else 0.0)
            return qb_s + rec_s - def_s

        raw = pass_delta(m_off, m_cov, cov_w)
        # 커버리지 붕괴: 숙련도가 낮은 커버리지에서 가끔 수비가 무너진다 (F11-3b)
        bust = 0.0
        p_bust = self.cp["bust_base"] * (F.mistake_factor(dfn.fam.get("cov_" + cov_type, F.BASE)) - 1) / 0.6
        if p_bust > 0 and rng.random() < p_bust:
            bust = self.cp["bust_size"]
            dfn.report["busts"] += 1
        d_pass = raw + bust - c.get("pass", 0.0) + call.anticip
        d_int = A.z(qb, "decision", N) - (A.z(defender, "ball_skills", N) if defender else 0.0) - c.get("int", 0.0)
        tacklers = self._on(g, d, "LB", "S", "CB")
        d_yac = A.mix(target, A.YAC, N) - A.unit(tacklers, A.TACKLE, N, 0.0) - c.get("yac", 0.0) + 0.5 * call.anticip
        home = self._home(g)
        drill = call.drill
        situ = self.situ_shift.get(call.dd, 0.0) + self.situ_gs.get(call.gs, 0.0) + self.situ_fz.get(call.fz, 0.0)

        zone2 = "red" if call.zone in ("red", "goal") else "open"
        pa = int(call.play_action)
        rates = T.lookup("pass_rates", depth, passing_down, pressure, zone2, pa, call.coverage)
        s_cmp = self.beta["completion"] * d_pass + home + drill   # 상황 보정은 야드(에어·YAC)에만
        p_cmp = 0.0 if throwaway else T.logit_shift(rates["cmp"], s_cmp)
        p_int = 0.0 if throwaway else T.logit_shift(max(rates["int"], 1e-4), -self.beta["interception"] * d_int)

        air = T.sample_quantile(T.lookup("pass_air", depth, zone2, pa, call.coverage), rng.random(),
                                self.beta["air"] * d_pass + situ)
        r = rng.random()
        plan.target, plan.defender = target, defender
        plan.interception = r < p_int
        plan.complete = (not plan.interception) and r < p_int + p_cmp
        if plan.complete:
            yac = T.sample_quantile(T.lookup("pass_yac", depth, zone2, call.coverage), rng.random(),
                                    self.beta["yac"] * d_yac + home + drill + situ)
            plan.yds = round(air + yac)
        else:
            plan.yds = round(air)
        plan.extra.update({"throwaway": throwaway, "d_pass": round(d_pass, 3), "d_rush": round(d_rush, 3),
                           "d_int": round(d_int, 3), "d_yac": round(d_yac, 3), "pocket": round(qb_pocket, 3),
                           "mobility": round(qb_move, 3)})
        if bust:
            plan.extra["bust"] = True
        if self.explain:
            # 완성 로짓 이동의 기여분 분해 (§8, T8): 능력치 + 숙련도(붕괴 포함) + 읽힘 + 훈련 + 홈 = 합계
            rating = pass_delta(1.0, 1.0, cov_w) - c.get("pass", 0.0)
            b = self.beta["completion"]
            other_cov = A.scheme("coverage", "zone" if cov_type == "man" else "man")
            fit_loss = max(0.0, pass_delta(1.0, 1.0, cov_w) - pass_delta(1.0, 1.0, other_cov))
            dfn.report["fit_loss"] += fit_loss
            plan.extra.update({"s_rating": round(b * rating, 4), "s_fam": round(b * (raw - (rating + c.get("pass", 0.0)) + bust), 4),
                               "s_anticip": round(b * call.anticip, 4), "s_drill": round(drill, 4),
                               "s_home": round(home, 4), "s_situ": 0.0, "s_total": round(s_cmp, 4),
                               "s_fit_def": round(-b * fit_loss, 4)})
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
            extra = {**getattr(self, "_scramble_extra", {}), "family": "scramble", "d_scr": round(d_scr, 3)}
            self._scramble_extra = {}
            return RunPlan(carrier=qb, rbw=None, yds=yds, extra=extra)

        call: Call = g.call or self.call_play(g, "run")
        sides = self._ctx(g)
        off, dfn = sides[o], sides[d]
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

        scheme = call.scheme
        front_name = getattr(g.team[d], "front", "4-3")
        m_run = off.m("run_" + scheme)
        m_front = dfn.m("front_43" if front_name == "4-3" else "front_34")
        blockers = self._on(g, o, "OL") + self._on(g, o, "TE")[:1]
        front = self._on(g, d, "DL", "LB")

        def run_delta(sch: str, mo: float, md: float) -> tuple[float, float]:
            d_line = A.unit(blockers, A.scheme("run_block", sch), N, m=mo) \
                - A.unit(front, A.scheme("run_def", sch), N, 0.2, md)
            d_carry = A.mix(carrier, A.scheme("carry", sch), N, mo) - A.unit(tacklers + front, A.TACKLE, N, 0.0)
            return d_line, 0.6 * d_line + 0.4 * d_carry

        d_line, raw = run_delta(scheme, m_run, m_front)
        d_run = raw - self.center.get("run", 0.0) + call.anticip
        dd2 = "short" if call.dd.endswith("s") else "std"
        table = T.lookup("run", family, call.zone, call.box, dd2)
        situ_r = self.situ_run.get(call.dd, 0.0)
        s_run = self.beta["run"] * d_run + home + call.drill + situ_r
        yds = round(T.sample_quantile(table["q"], rng.random(), s_run))
        rbw = {}
        for p in self._on(g, o, "OL"):
            rbw[p] = {"type": "OL", "won": rng.random() < 0.5 + 0.12 * d_line + (0.1 if yds > 3 else -0.1)}
        extra = {"family": family, "scheme": scheme, "box": call.box, "pers": call.personnel,
                 "d_run": round(d_run, 3), "b_pass": round(call.b_pass, 3), "xp": round(call.xp, 3), "dd": call.dd, "gs": call.gs}
        if self.explain:
            b = self.beta["run"]
            rating = run_delta(scheme, 1.0, 1.0)[1]
            other = run_delta("gap" if scheme == "zone" else "zone", 1.0, 1.0)[1]
            fit_loss = max(0.0, other - rating)
            off.report["fit_loss"] += fit_loss
            extra.update({"s_rating": round(b * (rating - self.center.get("run", 0.0)), 4),
                          "s_fam": round(b * (raw - rating), 4), "s_anticip": round(b * call.anticip, 4),
                          "s_drill": round(call.drill, 4), "s_home": round(home, 4), "s_situ": round(situ_r, 4),
                          "s_total": round(s_run, 4),
                          "s_fit_off": round(-b * fit_loss, 4)})
        return RunPlan(carrier=carrier, rbw=rbw, yds=yds, extra=extra)

    # ── 실수·리포트 (M4) ──────────────────────────────────
    def penalty_factor(self, g: "GameSim", side: str) -> float:
        """숙련도가 낮은 콜에서 반칙이 늘어난다 (F11-3b)."""
        call: Call | None = g.call
        if call is None or not self.sides:
            return 1.0
        if side == "offense":
            dom = ("pass_" + (call.intent or call.family)) if call.kind == "pass" else "run_" + call.scheme
            return F.mistake_factor(self.sides[g.o].fam.get(dom, F.BASE))
        dom = "cov_man" if call.coverage in MAN_COVERS else "cov_zone"
        return F.mistake_factor(self.sides[g.d].fam.get(dom, F.BASE))

    def report(self) -> dict:
        """경기 후 팀별 전술 리포트: 영역 사용량(숙련도), 콜 요약(스카우팅), 노출도·상대 적중률·읽힘·궁합 손실."""
        out = {}
        for s in self.sides:
            opp = self.sides[1 - s.t]
            r = dict(s.report)
            n = max(1, r["off_plays"])
            out[s.abbr] = {
                "usage": s.usage, "summary": s.summary, "lam": s.lam,
                "exposure": round(opp.knows_opp_off.exposure(), 1),
                "countered_rate": round(r["countered"] / n, 3),
                "anticip_mean": round(r["anticip"] / max(1, r["anticip_plays"]), 3),
                "anticip_plays": r["anticip_plays"], "fit_loss": round(r["fit_loss"], 2), "busts": r["busts"],
            }
        return out

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
