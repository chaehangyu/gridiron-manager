"""경기 컨텍스트: 양 팀 전술·숙련도·믿음·궁합·기록 (M4).

DataOutcome이 경기 첫 콜 때 만든다. 팀 정보는 TeamGameSim(build_team이 채움)에서 읽고, 없으면 리그 평균 전술.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...tactics import familiarity as F
from ...tactics.model import Tactics
from .. import adjust as A
from ..ai import coordinator as C

if TYPE_CHECKING:
    from ..skeleton.game import GameSim


def ai_ability(abbr: str) -> tuple[float, float]:
    """AI 코디네이터 능력 → (λ, τ). 팀마다 고정 (§6.4: λ 0.2–0.5, τ 0.01–0.04)."""
    h = int(hashlib.md5(abbr.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return round(0.2 + 0.3 * h, 3), round(0.04 - 0.03 * h, 4)


@dataclass
class Side:
    t: int
    abbr: str
    tactics: Tactics
    fam: dict[str, float]
    prep: dict
    lam: float
    tau: float
    knows_opp_off: C.OffenseBelief          # 이 팀(수비)이 상대 공격에 대해
    knows_opp_def: C.DefenseBelief          # 이 팀(공격)이 상대 수비에 대해
    fit_def: dict[str, float] = field(default_factory=dict)
    fit_off: dict[str, float] = field(default_factory=dict)
    usage: dict[str, float] = field(default_factory=dict)
    summary: dict = field(default_factory=lambda: {
        "off": {"plays": 0.0, "pass": 0.0, "xpass": 0.0, "fam": {}, "pa": 0.0},
        "def": {"pass_faced": 0.0, "runs_faced": 0.0, "cov": {}, "blitz": 0.0, "box": {}}})
    report: dict = field(default_factory=lambda: {"anticip": 0.0, "anticip_plays": 0, "fit_loss": 0.0,
                                                  "countered": 0, "off_plays": 0, "busts": 0})

    def m(self, domain: str) -> float:
        return F.multiplier(self.fam.get(domain, F.BASE))

    def add_usage(self, key: str, w: float = 1.0) -> None:
        self.usage[key] = self.usage.get(key, 0.0) + w


def _fit(g: "GameSim", t: int) -> tuple[dict, dict]:
    """경기 전 유닛 궁합 (리그 평균 0의 표준점수)."""
    N = g.norms
    depth = g.team[t].depth
    cbs = (depth.get("CB") or [])[:3] + (depth.get("S") or [])[:2]
    man = A.unit(cbs, A.scheme("coverage", "man"), N, 0.0)
    zone = A.unit(cbs, A.scheme("coverage", "zone"), N, 0.0)
    blitzers = (depth.get("LB") or [])[:2] + (depth.get("S") or [])[:1]
    bl = A.top_mean(blitzers, A.scheme("blitz_rush"), N, 1)
    fit_def = {"man": man, "zone": zone, "blitz": bl}
    qb = (depth.get("QB") or [None])[0]
    recs = (depth.get("WR") or [])[:3] + (depth.get("TE") or [])[:1]
    fit_off = {}
    for fam in C.PASS_FAMS:
        q = A.mix(qb, A.scheme("qb", fam), N) if qb else 0.0
        r = A.top_mean(recs, A.scheme("receiver", fam), N, 2) if recs else 0.0
        fit_off[fam] = q + r
    return fit_def, fit_off


def build(g: "GameSim", center: dict) -> list[Side]:
    p = C.params()
    sides = []
    for t in (0, 1):
        tg = g.team[t]
        tac = getattr(tg, "tactics", None) or Tactics()
        fam = dict(getattr(tg, "familiarity", None) or F.default())
        prep = dict(getattr(tg, "prep", None) or {})
        scout = getattr(tg, "scout", None) or {}   # 이 팀이 가진 상대에 대한 사전 정보
        lam = tac.predictability.lam
        tau = p["tau"]
        if getattr(tg, "ai_controlled", True):
            lam, tau = ai_ability(tg.abbr)
        kappa = p["kappa"] * prep.get("kappa_mult", 1.0)
        w = min(1.0, scout.get("w", 0.3))
        ob = C.OffenseBelief(kappa, scout.get("proe", 0.0), scout.get("fam"), w)
        db = C.DefenseBelief(kappa, scout.get("cov"), scout.get("blitz"), w)
        sides.append(Side(t, tg.abbr, tac, fam, prep, lam, tau, ob, db))
    for s in sides:
        s.fit_def, s.fit_off = _fit(g, s.t)
    _ = center
    return sides
