"""임시 능력치 생성기.

M3의 실측 능력치 파이프라인이 나오기 전까지 쓰는 **임시 값**이다.
- 실제 선수: 뎁스차트 순번·드래프트·경력으로 목표 포지션 평가(q)를 정하고, 포지션 프로필에 맞춰 능력치를 만든다.
- 가상 샘플 리그: 같은 함수를 무작위 q로 호출한다.

같은 선수 id면 항상 같은 값이 나오도록 id 기반 시드를 쓴다.
"""
from __future__ import annotations

import hashlib
import random

from ..domain.attributes import ATTR_KEYS, clamp
from ..domain.positions import Position
from .position_rating import weights

# 포지션별 신체 기준값 (F2-5b 앵커 기준 평균 선수). q가 높을수록 조금씩 오른다.
PHYSICAL_BASE: dict[Position, dict[str, float]] = {
    Position.QB: {"speed": 8.5, "acceleration": 9, "agility": 9, "strength": 7, "jumping": 7, "stamina": 13},
    Position.RB: {"speed": 14, "acceleration": 15, "agility": 14, "strength": 10, "jumping": 12, "stamina": 12},
    Position.FB: {"speed": 9, "acceleration": 10, "agility": 9, "strength": 13, "jumping": 8, "stamina": 12},
    Position.WR: {"speed": 15, "acceleration": 15, "agility": 14, "strength": 7, "jumping": 14, "stamina": 13},
    Position.TE: {"speed": 11, "acceleration": 11, "agility": 10, "strength": 12, "jumping": 12, "stamina": 13},
    Position.OT: {"speed": 4, "acceleration": 6, "agility": 7, "strength": 14, "jumping": 4, "stamina": 13},
    Position.OG: {"speed": 3.5, "acceleration": 5, "agility": 6, "strength": 15, "jumping": 3, "stamina": 13},
    Position.C: {"speed": 3.5, "acceleration": 5, "agility": 7, "strength": 14, "jumping": 3, "stamina": 13},
    Position.EDGE: {"speed": 11, "acceleration": 12, "agility": 10, "strength": 13, "jumping": 11, "stamina": 12},
    Position.DT: {"speed": 6, "acceleration": 8, "agility": 7, "strength": 16, "jumping": 6, "stamina": 11},
    Position.LB: {"speed": 11.5, "acceleration": 12, "agility": 11, "strength": 11, "jumping": 11, "stamina": 13},
    Position.CB: {"speed": 15.5, "acceleration": 15, "agility": 15, "strength": 6, "jumping": 14, "stamina": 13},
    Position.S: {"speed": 14, "acceleration": 14, "agility": 13, "strength": 8, "jumping": 13, "stamina": 13},
    Position.K: {"speed": 5, "acceleration": 5, "agility": 6, "strength": 5, "jumping": 5, "stamina": 12},
    Position.P: {"speed": 5, "acceleration": 5, "agility": 6, "strength": 5, "jumping": 5, "stamina": 12},
    Position.LS: {"speed": 4, "acceleration": 5, "agility": 5, "strength": 11, "jumping": 4, "stamina": 12},
}

# 포지션에서 주로 쓰지 않는 기술의 기본값 (F2-5a "사실상 없음"~"NFL 미달")
OFF_ROLE_DEFAULT = 3.0
MENTAL = ("football_iq", "composure", "determination", "leadership")
HIDDEN = ("consistency", "big_games", "durability", "recovery", "pain_tolerance")
RETURN_POSITIONS = {Position.WR, Position.RB, Position.CB, Position.S}


def seeded_rng(player_id: str, salt: str = "") -> random.Random:
    digest = hashlib.md5(f"{player_id}|{salt}".encode()).hexdigest()
    return random.Random(int(digest[:12], 16))


def generate_attributes(player_id: str, position: Position, quality: float,
                        years_exp: int = 3, height_in: int | None = None,
                        weight_lb: int | None = None) -> dict[str, float]:
    """목표 포지션 평가 `quality`(1–20)에 맞춘 능력치 한 벌."""
    rng = seeded_rng(player_id, "attrs")
    attrs: dict[str, float] = {k: OFF_ROLE_DEFAULT + rng.gauss(0, 1.0) for k in ATTR_KEYS}

    # 신체: 포지션 기준 + 품질 효과(작게) + 체격 보정
    phys = PHYSICAL_BASE[position]
    size_adj = 0.0
    if weight_lb is not None:
        typical = {Position.OT: 315, Position.OG: 315, Position.C: 305, Position.DT: 305, Position.EDGE: 260,
                   Position.TE: 250, Position.LB: 240, Position.FB: 245, Position.RB: 215, Position.QB: 220,
                   Position.WR: 200, Position.S: 205, Position.CB: 192}.get(position)
        if typical:
            size_adj = (weight_lb - typical) / 25.0
    for k, base in phys.items():
        v = base + 0.25 * (quality - 12.5) + rng.gauss(0, 1.3)
        if k in ("speed", "acceleration", "agility", "jumping"):
            v -= 0.8 * size_adj
        elif k == "strength":
            v += 0.8 * size_adj
        attrs[k] = v

    # 포지션 핵심 기술: 가중치가 클수록 q에 가깝게
    for key, w in weights(position):
        if key in phys:
            # 신체가 핵심인 경우에도 q 쪽으로 끌어당긴다
            attrs[key] = 0.5 * attrs[key] + 0.5 * (quality + rng.gauss(0, 1.2))
        else:
            attrs[key] = quality + rng.gauss(0, 1.3) - (0.0 if w >= 0.08 else 1.0)

    # 정신
    for k in MENTAL:
        attrs[k] = quality - 1.0 + rng.gauss(0, 1.8)
    attrs["leadership"] += min(4.0, 0.4 * years_exp) - 1.5
    attrs["football_iq"] += min(2.0, 0.25 * years_exp)
    # 숨김
    for k in HIDDEN:
        attrs[k] = 11.0 + rng.gauss(0, 2.8)

    # 리턴: 스피드·회피 기반 (리턴 가능 포지션만)
    if position in RETURN_POSITIONS:
        attrs["returning"] = 0.4 * attrs["speed"] + 0.3 * attrs["acceleration"] + 0.3 * max(attrs["elusiveness"], 6) + rng.gauss(0, 1.5) - 2
    # QB도 볼 안전성·시야는 어느 정도 있음
    if position == Position.QB:
        attrs["ball_security"] = max(attrs["ball_security"], quality - 2 + rng.gauss(0, 1.5))
    # 스킬 포지션은 볼 안전성 기본치
    if position in (Position.RB, Position.WR, Position.TE, Position.FB):
        attrs["ball_security"] = max(attrs["ball_security"], quality - 1 + rng.gauss(0, 1.5))
        attrs["elusiveness"] = max(attrs["elusiveness"], quality - 3 + rng.gauss(0, 1.5))
        attrs["break_tackle"] = max(attrs["break_tackle"], quality - 3 + rng.gauss(0, 1.5))
    # 수비수는 태클 기본치
    if position in (Position.EDGE, Position.DT, Position.LB, Position.CB, Position.S):
        attrs["tackling"] = max(attrs["tackling"], quality - 2 + rng.gauss(0, 1.5))
        attrs["pursuit"] = max(attrs["pursuit"], quality - 2 + rng.gauss(0, 1.5))
    # 라인맨은 반대 블로킹 기본치 (TE·RB 블로킹 등)
    if position in (Position.RB,):
        attrs["pass_block"] = max(attrs["pass_block"], quality - 4 + rng.gauss(0, 1.5))
    return {k: round(clamp(v), 2) for k, v in attrs.items()}


def provisional_quality(player_id: str, depth_rank: int | None, draft_round: int | None,
                        years_exp: int, on_practice_squad: bool = False, free_agent: bool = False) -> float:
    """실제 선수의 임시 목표 PR. M3 파이프라인이 대체한다."""
    rng = seeded_rng(player_id, "quality")
    if free_agent:
        q = 7.5
    elif on_practice_squad:
        q = 7.0
    elif depth_rank is None:
        q = 8.5
    else:
        q = {1: 13.0, 2: 10.5, 3: 9.0}.get(depth_rank, 8.5)
    if draft_round == 1:
        q += 1.0
    elif draft_round == 2:
        q += 0.5
    elif draft_round is None:
        q -= 0.5
    if years_exp == 0 and draft_round != 1:
        q -= 0.5
    elif 4 <= years_exp <= 9:
        q += 0.5
    return max(4.0, min(18.5, q + rng.gauss(0, 1.2)))
