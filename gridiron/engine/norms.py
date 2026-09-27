"""포지션별 능력치 기준값 (표준점수 계산용).

능력치 차이를 리그 전체 평균(12.5)과 비교하면 포지션마다 원래 낮은 능력치(QB 회피, OL 스피드 등)가
불리하게 계산된다. 그래서 리그 주전들의 포지션별 평균·표준편차로 표준점수를 만든다.
평균적인 주전끼리 붙으면 Δ≈0이 되어 실측 기준 분포가 그대로 재현된다.
"""
from __future__ import annotations

from statistics import mean, pstdev

from ..domain.attributes import ATTR_KEYS
from ..domain.models import League
from ..domain.positions import POSITION_TO_ENGINE

Norms = dict[str, dict[str, tuple[float, float]]]
SD_FLOOR = 1.0
_cache: dict[int, Norms] = {}


# 경기에서 실제로 필드에 서는 인원 (로테이션 포함). 실측 기준 분포도 이 평균 선수들의 결과다.
ROTATION = {"QB": 1, "RB": 2, "WR": 4, "TE": 2, "OL": 5, "DL": 6, "LB": 3, "CB": 4, "S": 3, "K": 1, "P": 1}


def compute_norms(league: League) -> Norms:
    from ..domain.depth import engine_depth

    key = id(league)
    if key in _cache:
        return _cache[key]
    groups: dict[str, list] = {}
    for team in league.teams.values():
        roster = {p.id: p for p in league.roster(team.abbr)}
        depth = engine_depth(team, roster)
        for pos, n in ROTATION.items():
            for pid in depth.get(pos, [])[:n]:
                p = roster[pid]
                if POSITION_TO_ENGINE[p.position] == pos:
                    groups.setdefault(pos, []).append(p)
    norms: Norms = {}
    for pos, players in groups.items():
        norms[pos] = {}
        for k in ATTR_KEYS:
            vals = [p.attributes[k] for p in players]
            norms[pos][k] = (mean(vals), max(SD_FLOOR, pstdev(vals)) if len(vals) > 1 else 2.0)
    _cache[key] = norms
    return norms
