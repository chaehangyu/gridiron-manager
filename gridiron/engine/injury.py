"""경기 중 부상 발생·진단 (PRD F10-1·F10-2·F10-4, M5b).

스냅당 위험 = 포지션 실측 위험 × 나이 × 내구성 × 재부상 × 강행 출전 × 피로 × 잔디. 부상이 나면 그 자리에서 부위와
결장 경기 수를 정한다(실측 부위별 분포, 회복력이 분위수를 당긴다). 다음 경기에 뛸 수 있는 경미한 부상은
부상 위험 정책에 따라 경기 중 복귀할 수 있다. 뇌진탕은 복귀 불가.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

import yaml

from ..config import CONFIG_DIR, DATA_DIR

GROUP = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "OL": "OL", "DL": "DL", "LB": "LB", "CB": "DB", "S": "DB",
         "K": "K", "P": "K", "KR": "WR", "PR": "WR"}


@lru_cache(maxsize=1)
def cfg() -> dict:
    return yaml.safe_load((CONFIG_DIR / "injuries.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads((DATA_DIR / "baseline" / "injuries.json").read_text(encoding="utf-8"))


def durability_mult(durability: float) -> float:
    return math.exp(-cfg()["durability_k"] * (durability - 10.5))


def label(part: str, missed: int) -> str:
    names = cfg()["labels"].get(part, ["부상", "부상"])
    return names[1] if missed >= data()["long"] else names[0]


def severity(missed: int) -> str:
    return "경미" if missed == 0 else "경미–중등" if missed <= 3 else "중등" if missed < data()["long"] else "심각"


class InjuryModel:
    def __init__(self, turf: bool = False, policies: dict[int, str] | None = None):
        c, d = cfg(), data()
        self.c = c
        self.hazard_base = {g: v * c["scale"] for g, v in d["hazard_per_snap"].items()}
        self.silent = {g: v * c["silent_factor"] for g, v in d["silent_hazard_per_snap"].items()}
        self.turf = c["turf"] if turf else 1.0
        self.policies = policies or {}
        parts = d["parts"]
        self.parts_by_group = {}
        for g in self.hazard_base:
            w = {p: v["by_group"].get(g, 0.0) for p, v in parts.items()}
            if sum(w.values()) == 0:
                w = {p: v["share"] for p, v in parts.items()}
            self.parts_by_group[g] = w
        self.hist = {p: sorted((int(k), n) for k, n in v["missed_hist"].items()) for p, v in parts.items()}

    def hazard(self, p, energy: float) -> tuple[float, float]:
        """(일반 부상 위험, 리포트 밖 중상 위험) — 스냅당."""
        g = GROUP.get(p.pos, "WR")
        m = self.c["age_rate"] ** (min(50.0, p.age) - 26) * p.inj_mult * self.turf
        if p.playing_through_injury:
            m *= self.c["playing_through"]
        m *= 1 + self.c["fatigue_k"] * (1 - max(0.0, min(1.0, energy)))
        return self.hazard_base.get(g, 0.0013) * m, self.silent.get(g, 0.0) * m

    def draw(self, p, rng, severe: bool = False) -> dict:
        g = GROUP.get(p.pos, "WR")
        long = data()["long"]
        if severe:
            part = rng.choice(list(self.c["severe_parts"]), lambda k: self.c["severe_parts"][k])
            missed = long
        else:
            w = self.parts_by_group[g]
            part = rng.choice(list(w), lambda k: w[k])
            rec = p.attributes.get("recovery", 10.5)
            u = rng.random() ** math.exp(self.c["recovery_k"] * (rec - 10.5))
            hist = self.hist[part]
            tot = sum(n for _, n in hist)
            acc, missed = 0.0, hist[-1][0]
            for k, n in hist:
                acc += n / tot
                if u <= acc:
                    missed = k
                    break
        season_out = False
        if missed >= long:
            if rng.random() < self.c["long_season_ending"] or severe and part in ("knee", "achilles"):
                season_out = True
                missed = 99
            else:
                lo, hi = self.c["long_weeks"]
                missed = lo + int(rng.random() * (hi - lo + 1))
        return {"part": part, "missed": missed, "season_out": season_out, "label": label(part, missed),
                "severity": severity(missed)}

    def may_return(self, p, inj: dict, team_num: int, rng) -> bool:
        if inj["missed"] > 0 or inj["part"] == "concussion":
            return False
        prob = self.c["in_game_return"].get(self.policies.get(team_num, "standard"), 0.65)
        return rng.random() < prob
