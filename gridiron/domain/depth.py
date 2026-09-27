"""자동 뎁스차트 (PRD F3-6)와 엔진용 뎁스 목록 변환."""
from __future__ import annotations

from ..ratings.position_rating import position_rating
from .models import Player, RosterStatus, Team
from .positions import (
    DEFENSE_SLOT_TO_ENGINE,
    OFFENSE_SLOT_TO_ENGINE,
    POSITION_TO_ENGINE,
    SLOT_POSITIONS,
    SPECIAL_SLOT_TO_ENGINE,
    Position,
    all_slots,
    defense_slots,
)

# 같은 유닛 안에서 한 선수를 두 슬롯의 주전으로 쓰지 않기 위한 슬롯 그룹
_EXCLUSIVE_GROUPS = [
    ["WR_X", "WR_Z", "WR_SLOT"],
    ["LT", "LG", "C", "RG", "RT"],
    ["LDE", "LDT", "RDT", "RDE", "NT", "WOLB", "SOLB"],
    ["WLB", "MLB", "SLB", "LILB", "RILB"],
    ["LCB", "RCB", "NB"],
    ["FS", "SS"],
]
DEPTH_PER_SLOT = 3


def _slot_score(p: Player, slot: str) -> float:
    eligible = SLOT_POSITIONS[slot]
    if slot in ("KR", "PR"):
        return p.attributes["returning"] * 0.6 + p.attributes["speed"] * 0.2 + p.attributes["ball_security"] * 0.2
    if slot == "H":
        return p.attributes["catching"] * 0.5 + p.attributes["composure"] * 0.5
    best = max(position_rating(p, pos) for pos in eligible)
    # 주 포지션이 아니면 감점 (보조 포지션 투입)
    if p.position not in eligible:
        best -= 3.0
    elif p.position != eligible[0]:
        best -= 0.5
    return best


def auto_depth_chart(team: Team, players: list[Player], keep_existing: bool = False) -> dict[str, list[str]]:
    """PR 기준으로 슬롯별 순번을 채운다. `keep_existing`이면 기존 순번을 앞에 두고 빈 곳만 채운다."""
    active = [p for p in players if p.roster_status == RosterStatus.ACTIVE and not p.injured]
    chart: dict[str, list[str]] = {}
    used_as_starter: dict[int, set[str]] = {i: set() for i in range(len(_EXCLUSIVE_GROUPS))}
    active_ids = {p.id for p in active}

    for slot in all_slots(team.front):
        eligible_pos = SLOT_POSITIONS[slot]
        existing = [pid for pid in team.depth_chart.get(slot, []) if pid in active_ids] if keep_existing else []
        group_idx = next((i for i, g in enumerate(_EXCLUSIVE_GROUPS) if slot in g), None)

        if slot in ("KR", "PR", "H"):
            pool = [p for p in active if p.position in eligible_pos]
        else:
            pool = [p for p in active if p.position in eligible_pos]
            if len(pool) < DEPTH_PER_SLOT and slot not in ("K", "P", "LS"):
                # 인원이 모자라면 비슷한 포지션 선수도 후보로
                pool = active
        ranked = sorted(pool, key=lambda p: _slot_score(p, slot), reverse=True)
        order = list(existing)
        for p in ranked:
            if len(order) >= DEPTH_PER_SLOT:
                break
            if p.id in order:
                continue
            if not order and group_idx is not None and p.id in used_as_starter[group_idx]:
                continue
            order.append(p.id)
        if order and group_idx is not None:
            used_as_starter[group_idx].add(order[0])
        chart[slot] = order
    return chart


def engine_depth(team: Team, players: dict[str, Player]) -> dict[str, list[str]]:
    """뎁스차트 → 엔진 포지션별 순번 목록.

    주전 슬롯 순서대로 먼저 넣고, 그 뒤에 슬롯별 백업, 마지막으로 뎁스차트에 없는 같은 포지션 선수를 PR 순으로 붙인다.
    엔진은 부상·피로로 빠진 선수를 이 순서대로 대체한다.
    """
    depth: dict[str, list[str]] = {k: [] for k in ("QB", "RB", "WR", "TE", "OL", "DL", "LB", "CB", "S", "K", "P", "KR", "PR")}
    slot_maps = {**OFFENSE_SLOT_TO_ENGINE, **DEFENSE_SLOT_TO_ENGINE, **SPECIAL_SLOT_TO_ENGINE}
    ordered_slots = [s for s in all_slots(team.front) if s in slot_maps]

    max_depth = max((len(team.depth_chart.get(s, [])) for s in ordered_slots), default=0)
    for rank in range(max_depth):
        for slot in ordered_slots:
            ids = team.depth_chart.get(slot, [])
            if rank < len(ids):
                pid = ids[rank]
                if pid not in players:
                    continue
                # 풀백 자리에 선 TE는 엔진에서 RB가 아니라 TE로만 쓴다 (러닝 플레이 볼 캐리어 방지)
                if slot == "FB" and players[pid].position not in (Position.FB, Position.RB):
                    continue
                eng = slot_maps[slot]
                if pid not in depth[eng]:
                    depth[eng].append(pid)

    roster = [p for p in players.values() if p.team == team.abbr and p.roster_status == RosterStatus.ACTIVE]
    for p in sorted(roster, key=position_rating, reverse=True):
        eng = POSITION_TO_ENGINE[p.position]
        if p.position == Position.LS:
            continue
        if p.id not in depth[eng]:
            depth[eng].append(p.id)
    # 리턴 요원 백업
    for eng in ("KR", "PR"):
        if len(depth[eng]) < 2:
            for p in sorted(roster, key=lambda x: x.attributes["returning"], reverse=True):
                if p.id not in depth[eng] and p.position in (Position.WR, Position.RB, Position.CB):
                    depth[eng].append(p.id)
                if len(depth[eng]) >= 3:
                    break
    return depth


__all__ = ["auto_depth_chart", "engine_depth", "defense_slots"]
