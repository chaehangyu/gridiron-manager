"""시드 고정 난수 (원본 common/random.ts 대응)."""
from __future__ import annotations

import math
import random
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")


class Rng:
    def __init__(self, seed: int | None = None) -> None:
        self._r = random.Random(seed)

    def random(self) -> float:
        return self._r.random()

    def rand_int(self, a: int, b: int) -> int:
        """원본 randInt: a와 b 모두 포함. a > b여도 원본과 같은 식으로 동작한다."""
        return math.floor(self._r.random() * (1 + b - a)) + a

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        return self._r.gauss(mu, sigma)

    def trunc_gauss(self, mu: float = 0.0, sigma: float = 1.0,
                    lower: float = -math.inf, upper: float = math.inf) -> float:
        for _ in range(1_000_000):
            x = self._r.gauss(mu, sigma)
            if lower <= x <= upper:
                return x
        raise RuntimeError("Could not find valid random number")

    def choice(self, items: Sequence[T], weights: Callable[[T], float] | Sequence[float] | None = None) -> T:
        if not items:
            raise ValueError("empty choice")
        if weights is None:
            return items[math.floor(self._r.random() * len(items))]
        ws = [weights(x) for x in items] if callable(weights) else list(weights)
        ws = [w if (w > 0 and not math.isnan(w)) else 5e-324 for w in ws]
        total = sum(ws)
        r = self._r.random() * total
        acc = 0.0
        for item, w in zip(items, ws):
            acc += w
            if r < acc:
                return item
        return items[-1]

    def shuffle(self, items: list) -> None:
        n = len(items)
        for i in range(1, n):
            j = self.rand_int(0, i)
            if j != i:
                items[i], items[j] = items[j], items[i]


def bound(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x
