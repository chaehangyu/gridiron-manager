"""경기 중 학습하는 코디네이터 (ENGINE_DESIGN §6, PRD F4·F5-7, M4).

구성
- 상황 버킷: 다운·거리 8 × 필드 5 × 점수·시간 4 × 공격 퍼스넬. 관측은 계층 공유(세부 1, 퍼스넬 제외 0.5, 다운만 0.25).
- 수비의 믿음 `OffenseBelief`: 공격의 "기대 대비 패스 편차"(PROE)와 패스 패밀리 비중. 중립값은 리그 xpass를
  퍼스넬로 갱신한 값(E10: 퍼스넬이 드러내는 정보는 리그 지식으로 항상 쓴다).
- 공격의 믿음 `DefenseBelief`: 수비의 커버리지·블리츠·박스 비중.
- 콜 선택: π(c) ∝ B(c) · exp(λ · [ΔV(c) + V_fit(c)] / τ)
    B: 팀 정체성(실측 분포 × 전술 배율), ΔV: 지금 믿음으로 본 기대 EPA − 중립 믿음으로 본 기대 EPA,
    V_fit: 우리 유닛이 그 콜에 맞는 정도. 중립 믿음·평균 로스터에서 π = B 이므로 실측 보정이 유지된다.
    (§6.4의 `(1−λ)B + λ·softmax`를 이 형태로 바꾼 이유: 실측 정체성 분포에는 평균 팀의 대응이 이미 들어 있어서,
    softmax 최선 대응을 그대로 섞으면 리그 평균 통계가 무너진다. M4 구현 노트 §15.)
- 읽힘 효과(경로 ②): 수비 믿음이 중립보다 그 종류(패스/런)를 더 예상할수록 결과가 나빠진다.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from typing import TYPE_CHECKING

from ...baseline import tables as T
from ...config import DATA_DIR, load
from ...tactics.model import MAN_COVERS, Tactics

if TYPE_CHECKING:
    from ..skeleton.game import GameSim

PASS_FAMS = ("screen", "quick", "inter", "deep")
RUN_FAMS = ("inside", "outside")
COVERS = ("C0", "C1", "2M", "C2", "C3", "QTR")
BOXES = ("light", "normal", "heavy")


@lru_cache(maxsize=1)
def payoff() -> dict:
    return json.loads((DATA_DIR / "baseline" / "payoff.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def params() -> dict:
    return load("engine")["coordinator"]


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


# ── 상황 버킷 ─────────────────────────────────────────────────────
def dd8(down: int, togo: float) -> str:
    if down == 1:
        return "1"
    if down >= 4:
        return "4"
    return f"{down}" + ("s" if togo <= 3 else ("m" if togo <= 7 else "l"))


def field5(yardline_100: float) -> str:
    if yardline_100 >= 90:
        return "backed"
    if yardline_100 >= 50:
        return "own"
    if yardline_100 > 20:
        return "opp"
    if yardline_100 > 5:
        return "red"
    return "goal"


def game_state(score_diff: float, half_sec: float, second_half: bool) -> str:
    if half_sec <= 120:
        return "two_min"
    if second_half and score_diff >= 9:
        return "lead"
    if second_half and score_diff <= -9:
        return "trail"
    return "close"


# ── 믿음 ─────────────────────────────────────────────────────────
class OffenseBelief:
    """수비가 가진, 상대 공격에 대한 믿음."""

    # 관측 가중 (세부, 퍼스넬 제외, 다운 수준). 설계(§6.2)의 1/0.5/0.25는 한 경기 60여 플레이로는 상위 단계가
    # 거의 배우지 못해(다운 수준 표본 6–7) 모든 단계에 1을 준다. 세부 단계는 κ/2로 윗단계를 빌려 쓴다.
    SHARE = (1.0, 1.0, 1.0)

    def __init__(self, kappa: float, prior_dev: float, prior_fam: dict[str, float] | None, w_scout: float) -> None:
        self.kappa = kappa
        self.prior_dev = w_scout * prior_dev
        self.prior_fam = prior_fam or {}
        self.w_scout = w_scout
        self.n = [{}, {}, {}]
        self.s = [{}, {}, {}]
        self.fam: dict[str, dict[str, float]] = {}

    @staticmethod
    def keys(dd: str, fz: str, gs: str, pers: str) -> tuple:
        return ((dd, fz, gs, pers), (dd, fz, gs), (dd,))

    def dev(self, keys: tuple) -> float:
        """계층 수축 추정: 다운 수준(사전값을 κ개 가상 표본으로) → 퍼스넬 제외 → 세부(윗단계를 κ/2개로)."""
        est = self.prior_dev
        for lvl in (2, 1, 0):
            k = self.kappa if lvl == 2 else 0.5 * self.kappa
            n = self.n[lvl].get(keys[lvl], 0.0)
            s = self.s[lvl].get(keys[lvl], 0.0)
            est = (k * est + s) / (k + n)
        return est

    def b_pass(self, keys: tuple, neutral: float) -> float:
        return min(0.98, max(0.02, neutral + self.dev(keys)))

    def fam_probs(self, dd: str, league: dict[str, float]) -> dict[str, float]:
        base = {f: (1 - self.w_scout) * league.get(f, 0.0) + self.w_scout * self.prior_fam.get(f, league.get(f, 0.0))
                for f in PASS_FAMS}
        cnt = self.fam.get(dd, {})
        n = sum(cnt.values())
        tot = {f: self.kappa * base[f] + cnt.get(f, 0.0) for f in PASS_FAMS}
        z = sum(tot.values()) or 1.0
        _ = n
        return {f: v / z for f, v in tot.items()}

    def observe(self, keys: tuple, is_pass: bool, neutral: float, family: str | None) -> None:
        x = (1.0 if is_pass else 0.0) - neutral
        for lvl, w in enumerate(self.SHARE):
            self.n[lvl][keys[lvl]] = self.n[lvl].get(keys[lvl], 0.0) + w
            self.s[lvl][keys[lvl]] = self.s[lvl].get(keys[lvl], 0.0) + w * x
        if is_pass and family in PASS_FAMS:
            d = self.fam.setdefault(keys[2][0], {})
            d[family] = d.get(family, 0.0) + 1.0

    def exposure(self) -> float:
        """노출도 0–100: 상대가 추정한 우리 패스 성향 편차(스카우팅 사전값 포함)의 크기, 다운 수준 표본 가중. 편차 0.2 = 100.

        (§6.8의 KL 발산은 경기 중 표본이 작아 거의 0에 머물러, 사용자에게 보이는 지표로는 편차 크기를 쓴다.)"""
        tot, w = 0.0, 0.0
        for key, n in self.n[2].items():
            tot += n * abs(self.dev((None, None, key)))
            w += n
        return min(100.0, 100 * (tot / w) / 0.20) if w else 0.0


class DefenseBelief:
    """공격이 가진, 상대 수비에 대한 믿음 (다운 수준)."""

    def __init__(self, kappa: float, prior_cov: dict[str, float] | None, prior_blitz: float | None,
                 w_scout: float) -> None:
        self.kappa = kappa
        self.prior_cov = prior_cov or {}
        self.prior_blitz = prior_blitz
        self.w = w_scout
        self.cov: dict[str, dict[str, float]] = {}
        self.blitz: dict[str, list[float]] = {}
        self._base: dict = {}
        self.box_n = 0.0
        self.box_dev = 0.0    # Σ (관측 무거움 − 가벼움) − (실측 기대 무거움 − 가벼움)

    def calls(self, dd: str, league_cov: dict[str, float], league_blitz: dict[str, float]) -> dict[tuple, float]:
        key = (dd, id(league_cov))
        base = self._base.get(key)
        if base is None:
            base = self._base[key] = {c: (1 - self.w) * league_cov.get(c, 0.0)
                                      + self.w * self.prior_cov.get(c, league_cov.get(c, 0.0)) for c in COVERS}
        cnt = self.cov.get(dd, {})
        tot = {c: self.kappa * base[c] + cnt.get(c, 0.0) for c in COVERS}
        z = sum(tot.values()) or 1.0
        bl = self.blitz.get(dd, [0.0, 0.0])
        out = {}
        for c in COVERS:
            pb0 = league_blitz.get(c, 0.3)
            if self.prior_blitz is not None:
                pb0 = (1 - self.w) * pb0 + self.w * self.prior_blitz * pb0 / 0.3
            pb = (self.kappa * pb0 + bl[0]) / (self.kappa + bl[1])
            out[(c, 1)] = tot[c] / z * pb
            out[(c, 0)] = tot[c] / z * (1 - pb)
        return out

    def box_tilt(self) -> float:
        """무거운 박스 − 가벼운 박스 비율의 실측 기대 대비 편차 (수축)."""
        return self.box_dev / (self.box_n + self.kappa)

    def observe(self, dd: str, cov: str, blitz: int, box: str, expected_box: dict[str, float]) -> None:
        d = self.cov.setdefault(dd, {})
        d[cov] = d.get(cov, 0.0) + 1.0
        b = self.blitz.setdefault(dd, [0.0, 0.0])
        b[0] += blitz
        b[1] += 1
        tot = sum(expected_box.values()) or 1.0
        exp = (expected_box.get("heavy", 0.0) - expected_box.get("light", 0.0)) / tot
        self.box_dev += (box == "heavy") - (box == "light") - exp
        self.box_n += 1


# ── 콜 기울이기 ────────────────────────────────────────────────────
def tilt(base: dict, gain: dict, lam: float, tau: float) -> dict:
    """π(x) ∝ B(x)·exp(λ·gain(x)/τ). gain은 B 가중 평균을 빼서 '재분배'만 하게 한다."""
    tot_b = sum(base.values()) or 1.0
    mean = sum(base[k] * gain.get(k, 0.0) for k in base) / tot_b
    out = {k: v * math.exp(min(30.0, lam * (gain.get(k, 0.0) - mean) / tau)) for k, v in base.items()}
    z = sum(out.values()) or 1.0
    return {k: v / z for k, v in out.items()}


@lru_cache(maxsize=1)
def _flat() -> dict[str, dict[tuple, float]]:
    """상성표를 {패밀리: {(커버리지, 블리츠): EPA}}로 펼쳐 둔다 (플레이마다 조회하므로)."""
    po = payoff()["pass"]
    return {f: {(c, b): po[f][c][str(b)] for c in COVERS for b in (0, 1)} for f in PASS_FAMS}


def pass_value(fam_probs: dict[str, float], call: tuple) -> float:
    P = _flat()
    return sum(p * P[f][call] for f, p in fam_probs.items())


def family_value(fam: str, calls: dict[tuple, float]) -> float:
    P = _flat()[fam]
    return sum(p * P[k] for k, p in calls.items())


def run_value(fam: str, box_probs: dict[str, float]) -> float:
    po = payoff()["run"][fam]
    return sum(p * po[b] for b, p in box_probs.items())


def identity_coverage(dd_tab: str, pers: str, tac: Tactics, situ: dict) -> dict[tuple, float]:
    """수비 정체성 B_D(커버리지, 블리츠) = 실측 분포 × 전술 배율."""
    cov = T.lookup("coverage", dd_tab, pers)
    d = tac.defense
    out = {}
    blitz_mult = d.blitz * situ.get("blitz", 1.0)
    for c in COVERS:
        w = cov.get(c, 0.0) * d.coverage.get(c, 1.0) * math.exp(0.9 * d.man_zone * (1 if c in MAN_COVERS else -1))
        pb = T.lookup("blitz", c, dd_tab)
        odds = pb / max(1e-4, 1 - pb) * blitz_mult
        pb = odds / (1 + odds)
        out[(c, 1)] = w * pb
        out[(c, 0)] = w * (1 - pb)
    z = sum(out.values()) or 1.0
    return {k: v / z for k, v in out.items()}


def league_coverage(dd_tab: str, pers: str) -> tuple[dict[str, float], dict[tuple, float], dict[str, float]]:
    cov = T.lookup("coverage", dd_tab, pers)
    blitz = {c: T.lookup("blitz", c, dd_tab) for c in COVERS}
    calls = {}
    for c in COVERS:
        calls[(c, 1)] = cov.get(c, 0.0) * blitz[c]
        calls[(c, 0)] = cov.get(c, 0.0) * (1 - blitz[c])
    z = sum(calls.values()) or 1.0
    return cov, {k: v / z for k, v in calls.items()}, blitz


def neutral_pass(xp: float, dd_tab: str, pers: str) -> float:
    """리그 xpass를 퍼스넬로 갱신 (E10)."""
    pp = T.lookup("personnel", "pass", dd_tab).get(pers, 1e-3)
    pr = T.lookup("personnel", "run", dd_tab).get(pers, 1e-3)
    return xp * pp / (xp * pp + (1 - xp) * pr)


def situation_key(dd: str, fz: str) -> str:
    return f"{dd}|{fz}"


def situational(tac: Tactics, dd: str, fz: str) -> dict:
    s = tac.situational
    out = {}
    for key in (dd, situation_key(dd, fz)):
        out.update(s.get(key) or {})
    return out


def tendency_break(level: str, dev: float) -> float:
    """공격의 자기 노출 감시: 믿음 편차가 기준을 넘으면 반대쪽으로 로짓을 민다."""
    if level == "off":
        return 0.0
    thr, k = (0.10, 4.0) if level == "normal" else (0.06, 7.0)
    if abs(dev) <= thr:
        return 0.0
    return -math.copysign(k * (abs(dev) - thr), dev)


def half_info(g: "GameSim") -> tuple[float, bool]:
    from .decisions import clock_state
    _, half_sec = clock_state(g)
    quarter = len(g.team[0].stat["ptsQtrs"])
    return half_sec, quarter >= 3
