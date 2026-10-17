"""역할 평가 (PRD F2-6). 같은 포지션이라도 역할마다 중요한 능력치가 다르다.

초기 역할은 역할 평가가 가장 높은 역할로 정한다 (F2-6b의 실제 사용 패턴 추정은 Post-MVP에서 데이터로 보강).
"""
from __future__ import annotations

from functools import lru_cache

from ..config import load
from ..domain.models import Player
from ..domain.positions import Position

ROLE_GROUP = {Position.QB: "QB", Position.RB: "RB", Position.FB: "RB", Position.WR: "WR", Position.TE: "TE",
              Position.OT: "OL", Position.OG: "OL", Position.C: "OL", Position.EDGE: "EDGE", Position.DT: "DT",
              Position.LB: "LB", Position.CB: "CB", Position.S: "S"}


@lru_cache(maxsize=1)
def roles() -> dict:
    return load("roles")


def role_ratings(p: Player) -> dict[str, tuple[str, float]]:
    """역할 키 → (이름, 1–20 평가). 역할이 없는 포지션(K·P·LS)은 빈 dict."""
    group = ROLE_GROUP.get(p.position)
    if group is None:
        return {}
    out = {}
    for key, spec in roles()[group].items():
        w = spec["w"]
        tot = sum(w.values())
        out[key] = (spec["name"], round(sum(p.attributes[k] * v for k, v in w.items()) / tot, 1))
    return out


def best_role(p: Player) -> tuple[str, str, float] | None:
    rr = role_ratings(p)
    if not rr:
        return None
    key = max(rr, key=lambda k: rr[k][1])
    return key, rr[key][0], rr[key][1]
