"""기준 분포 테이블 런타임 (pandas 없이 동작).

- `lookup(table, *keys)`: 세부 칸이 없으면 뒤쪽 키부터 '*'로 바꿔 상위 칸을 찾는다 (ENGINE_DESIGN §5.3 수축).
- `sample_quantile(q, u, shift)`: 분위수 이동 샘플링 u' = Φ(Φ⁻¹(u) + shift).
"""
from __future__ import annotations

import json
from bisect import bisect_left
from functools import lru_cache
from statistics import NormalDist

from ..config import DATA_DIR

_N = NormalDist()


@lru_cache(maxsize=1)
def tables() -> dict:
    return json.loads((DATA_DIR / "baseline" / "tables.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def pcts() -> list[float]:
    return [p / 100 for p in tables()["meta"]["pcts"]]


def lookup(name: str, *keys) -> object:
    table = tables()[name]
    keys = [str(k) for k in keys]
    for i in range(len(keys), -1, -1):
        k = "|".join(keys[:i] + ["*"] * (len(keys) - i))
        if k in table:
            return table[k]
    raise KeyError(f"{name}: {keys}")


def shift_u(u: float, shift: float) -> float:
    if shift == 0.0:
        return u
    u = min(max(u, 1e-6), 1 - 1e-6)
    return _N.cdf(_N.inv_cdf(u) + shift)


def sample_quantile(q: list[float], u: float, shift: float = 0.0) -> float:
    """분위수 표 q(pcts 격자)에서 u(0–1)를 shift만큼 옮겨 값을 뽑는다 (선형 보간)."""
    u = shift_u(u, shift)
    ps = pcts()
    i = bisect_left(ps, u)
    if i <= 0:
        return q[0]
    if i >= len(ps):
        return q[-1]
    p0, p1 = ps[i - 1], ps[i]
    w = (u - p0) / (p1 - p0) if p1 > p0 else 0.0
    return q[i - 1] + w * (q[i] - q[i - 1])


def logit_shift(p: float, shift: float) -> float:
    import math
    p = min(max(p, 1e-6), 1 - 1e-6)
    x = math.log(p / (1 - p)) + shift
    return 1 / (1 + math.exp(-x))


def choose(dist: dict[str, float], u: float) -> str:
    acc = 0.0
    total = sum(dist.values())
    for k, v in dist.items():
        acc += v / total
        if u < acc:
            return k
    return next(reversed(dist))
