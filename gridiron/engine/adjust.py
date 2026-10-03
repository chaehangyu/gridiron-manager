"""능력치 → 표준점수 유닛 점수와 Δ (ENGINE_DESIGN §4.3).

z = (유효 능력치 − 포지션 기준 평균) / 포지션 기준 표준편차.
유효 능력치 A_eff = A × m (m: 콜 영역 숙련도 배율 × 선수 컨디션 배율, M4).
콜별 가중치는 config/scheme_weights.yaml (`scheme(...)`).
"""
from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from ..config import load

if TYPE_CHECKING:
    from .skeleton.types import PlayerGameSim

DEFAULT = (12.5, 2.0)
EXPECTED_MIN = {1: 0.0, 2: -0.564, 3: -0.846, 4: -1.029, 5: -1.163, 6: -1.267, 7: -1.352, 8: -1.424,
                9: -1.485, 10: -1.539, 11: -1.586}


@lru_cache(maxsize=1)
def _scheme() -> dict:
    return load("scheme_weights")


def scheme(group: str, call: str = "any") -> dict[str, float]:
    """콜별 능력치 가중치 (예: scheme("run_block", "gap"))."""
    return _scheme()[group][call]


def a(p: "PlayerGameSim", key: str, m: float = 1.0) -> float:
    """유효 능력치 (1–20 기준). m은 숙련도 배율, p.cond는 컨디션 배율.

    Football GM의 에너지 값은 교체 판단용이라 경기력에 곱하지 않는다 (교체 없는 OL이 경기 내내 0으로 떨어짐).
    """
    return p.attributes.get(key, 12.5) * m * p.cond


def z(p: "PlayerGameSim", key: str, norms: dict | None, m: float = 1.0) -> float:
    try:
        mu, sd = norms[p.pos][key]
    except (KeyError, TypeError):
        mu, sd = DEFAULT
    return (p.attributes.get(key, 12.5) * m * p.cond - mu) / sd


def mix(p: "PlayerGameSim", weights: dict[str, float], norms: dict | None, m: float = 1.0) -> float:
    attrs, mc = p.attributes, m * p.cond
    try:
        pn = norms[p.pos]
    except (KeyError, TypeError):
        pn = {}
    s = tot = 0.0
    for k, w in weights.items():
        mu, sd = pn.get(k, DEFAULT)
        s += (attrs.get(k, 12.5) * mc - mu) / sd * w
        tot += w
    return s / tot


def unit(players: list["PlayerGameSim"], weights: dict[str, float], norms: dict | None, weakest: float = 0.3,
         m: float = 1.0) -> float:
    """유닛 점수 = (1−weakest)·평균 + weakest·최저 (약한 고리 반영). 선수가 없으면 큰 불이익."""
    if not players:
        return -2.0
    vals = [mix(p, weights, norms, m) for p in players]
    mean = sum(vals) / len(vals)
    # 최저값은 인원이 많을수록 원래 낮으므로, 표준정규 n명 최저값의 기대치를 빼서 평균 유닛이 0이 되게 한다
    return (1 - weakest) * mean + weakest * (min(vals) - EXPECTED_MIN.get(len(vals), -1.6))


def top_mean(players: list["PlayerGameSim"], weights: dict[str, float], norms: dict | None, n: int,
             m: float = 1.0) -> float:
    if not players:
        return -2.0
    vals = sorted((mix(p, weights, norms, m) for p in players), reverse=True)[:n]
    return sum(vals) / len(vals)


PASS_BLOCK = {"pass_block": 0.7, "strength": 0.15, "agility": 0.15}
RUN_BLOCK = {"run_block": 0.6, "strength": 0.2, "agility": 0.2}
RUSH = {"finesse_rush": 0.35, "power_rush": 0.35, "acceleration": 0.15, "strength": 0.15}
RUN_DEF = {"run_stop": 0.5, "block_shedding": 0.3, "strength": 0.2}
TACKLE = {"tackling": 0.6, "pursuit": 0.4}
MAN = {"man_coverage": 0.5, "press": 0.2, "speed": 0.3}
ZONE = {"zone_coverage": 0.5, "football_iq": 0.3, "ball_skills": 0.2}
CARRY = {"vision": 0.3, "elusiveness": 0.25, "break_tackle": 0.25, "speed": 0.2}
YAC = {"elusiveness": 0.4, "break_tackle": 0.3, "speed": 0.3}
POCKET = {"pocket_presence": 0.6, "elusiveness": 0.4}
MOBILITY = {"speed": 0.5, "elusiveness": 0.3, "acceleration": 0.2}
QB_BY_DEPTH = {
    "screen": {"short_accuracy": 0.7, "decision": 0.3},
    "quick": {"short_accuracy": 0.6, "decision": 0.4},
    "inter": {"medium_accuracy": 0.6, "decision": 0.25, "pocket_presence": 0.15},
    "deep": {"deep_accuracy": 0.5, "throw_power": 0.3, "decision": 0.2},
}
REC_BY_DEPTH = {
    "screen": {"catching": 0.4, "elusiveness": 0.3, "speed": 0.3},
    "quick": {"route_running": 0.4, "catching": 0.35, "release": 0.25},
    "inter": {"route_running": 0.4, "catching": 0.3, "release": 0.15, "contested_catch": 0.15},
    "deep": {"speed": 0.3, "route_running": 0.25, "contested_catch": 0.25, "catching": 0.2},
}
MAN_COVERAGES = {"C0", "C1", "2M"}
