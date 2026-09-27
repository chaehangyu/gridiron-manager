"""유닛 종합치 (원본 getCompositeFactor.ts, index.ts의 COMPOSITE_FACTOR_OPTIONS)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .types import PlayerGameSim

POSITIONS = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "CB", "S", "K", "P", "KR", "PR"]


def get_players(on_field: dict[str, list[PlayerGameSim]], positions: list[str] = POSITIONS) -> list[PlayerGameSim]:
    out: list[PlayerGameSim] = []
    for pos, ps in on_field.items():
        if pos in positions and ps:
            out.extend(ps)
    return out


@dataclass(frozen=True)
class CompositeFactorParams:
    positions: tuple[str, ...]
    order: Callable[[PlayerGameSim], float]
    weights_main: tuple[float, ...]
    weights_bonus: tuple[float, ...]
    value: Callable[[PlayerGameSim], float]


def composite_factor(on_field: dict[str, list[PlayerGameSim]], params: CompositeFactorParams) -> float:
    """상위 선수에게 큰 가중치. weights_bonus는 분모에 넣지 않는 추가 보너스."""
    max_num = len(params.weights_main) + len(params.weights_bonus)
    players = get_players(on_field, list(params.positions))
    players.sort(key=params.order, reverse=True)
    n = min(len(players), max_num)
    if n == 0:
        return 0.0
    num = den = 0.0
    for i in range(n):
        main = i < len(params.weights_main)
        w = params.weights_main[i] if main else params.weights_bonus[i - len(params.weights_main)]
        num += w * params.value(players[i])
        if main:
            den += w
    return num / den


FACTOR_OPTIONS: dict[str, CompositeFactorParams] = {
    "receiving": CompositeFactorParams(("WR", "TE", "RB"), lambda p: p.ovrs["WR"], (5, 3, 2), (0.5, 0.25),
                                       lambda p: p.ovrs["WR"] / 100),
    "rushing": CompositeFactorParams(("RB", "WR", "QB"), lambda p: p.ovrs["RB"], (1,), (0.1,),
                                     lambda p: (p.ovrs["RB"] / 100 + p.composite["rushing"]) / 2),
    "passRushing": CompositeFactorParams(("DL", "LB"), lambda p: p.ovrs["DL"], (5, 4, 3, 2, 1), (),
                                         lambda p: (p.ovrs["DL"] / 100 + p.composite["passRushing"]) / 2),
    "runStopping": CompositeFactorParams(("DL", "LB", "S"), lambda p: p.ovrs["DL"], (5, 4, 3, 2, 2, 1, 1), (0.5, 0.5),
                                         lambda p: (p.ovrs["DL"] / 100 + p.composite["runStopping"]) / 2),
    "passCoverage": CompositeFactorParams(("CB", "S", "LB"), lambda p: p.ovrs["CB"], (5, 4, 3, 2, 1, 1), (0.5, 0.5),
                                          lambda p: (p.ovrs["CB"] / 100 + p.composite["passCoverage"]) / 2),
    "tackling": CompositeFactorParams(("DL", "LB", "S"), lambda p: p.ovrs["LB"], (5, 4, 3, 2, 1), (),
                                      lambda p: (p.ovrs["LB"] / 100 + p.composite["tackling"]) / 2),
}

_BLOCK_WEIGHTS_MAIN = (5, 4, 3, 3, 3)
_BLOCK_WEIGHTS_BONUS = (1, 0.5)


def blocking_factors(on_field: dict[str, list[PlayerGameSim]]) -> tuple[float, float]:
    """(패스 블록, 런 블록). 상위 블로커 5명 + TE·RB 보너스."""
    players = get_players(on_field, ["OL", "TE", "RB"])
    players.sort(key=lambda p: p.ovrs["OL"], reverse=True)
    n = min(len(players), len(_BLOCK_WEIGHTS_MAIN) + len(_BLOCK_WEIGHTS_BONUS))
    if n == 0:
        return 0.0, 0.0
    pb = rb = den = 0.0
    for i in range(n):
        main = i < len(_BLOCK_WEIGHTS_MAIN)
        w = _BLOCK_WEIGHTS_MAIN[i] if main else _BLOCK_WEIGHTS_BONUS[i - len(_BLOCK_WEIGHTS_MAIN)]
        p = players[i]
        ovr = p.ovrs["OL"] / 100
        pb += w * ((ovr + p.composite["passBlocking"]) / 2)
        rb += w * ((ovr + p.composite["runBlocking"]) / 2)
        if main:
            den += w
    return pb / den, rb / den
