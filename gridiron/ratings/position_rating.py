"""포지션 평가(PR, 1–20 소수 1자리) — PRD F2-3."""
from __future__ import annotations

from functools import lru_cache

from ..config import load
from ..domain.attributes import stars
from ..domain.models import Player
from ..domain.positions import Position


@lru_cache(maxsize=None)
def weights(position: Position) -> tuple[tuple[str, float], ...]:
    raw: dict[str, float] = load("position_weights")[position.value]
    total = sum(raw.values())
    return tuple((k, v / total) for k, v in raw.items())


def position_rating(player: Player, position: Position | None = None) -> float:
    pos = position or player.position
    return round(sum(w * player.attributes[k] for k, w in weights(pos)), 1)


def all_position_ratings(player: Player) -> dict[Position, float]:
    """모든 포지션의 PR (F2-3d: 포지션 변경·긴급 투입 판단용)."""
    return {pos: position_rating(player, pos) for pos in Position}


def star_rating(player: Player) -> float:
    return stars(position_rating(player))
