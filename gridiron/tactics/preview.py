"""전술 변경 미리보기 (PRD F4-8d·F5-7c).

- 노출도 추정: 전술이 리그 평균에서 얼마나 치우쳤는지(상대가 읽기 쉬운 정도) 0–100. 경기 중 실제 노출도는
  상대 코디네이터의 믿음으로 계산되지만(ENGINE_DESIGN §6), 치우침이 클수록 빨리 읽힌다는 같은 원리를 쓴다.
- 예상 효과: 다음 상대와 같은 시드로 엔진 경기를 N번씩 돌려 현재 전술과 새 전술의 득점·실점을 비교한다
  (공통 난수라 차이의 잡음이 작다).
"""
from __future__ import annotations

import math
import zlib

from .model import LEAGUE_PASS_RATE, MAN_COVERS, Tactics

BREAK_RELIEF = {"off": 1.0, "normal": 0.85, "aggressive": 0.7}


def exposure_estimate(t: Tactics) -> tuple[float, list[str]]:
    """치우침 점수 → 노출도 0–100과 '예측당하기 쉬운 설정' 경고."""
    o, d = t.offense, t.defense
    parts: list[tuple[str, float]] = []
    parts.append(("런/패스 비율", abs(o.pass_shift()) * 1.2))
    for key, label in (("short", "숏 패스"), ("mid", "미들 패스"), ("deep", "딥 패스"), ("play_action", "플레이액션"),
                       ("screen", "스크린")):
        parts.append((label, abs(math.log(max(0.05, getattr(o, key)))) * 0.35))
    if o.personnel:
        parts.append(("퍼스넬", max(abs(math.log(max(0.05, v))) for v in o.personnel.values()) * 0.25))
    if d.coverage:
        parts.append(("커버리지 쏠림", max(abs(math.log(max(0.05, v))) for v in d.coverage.values()) * 0.4))
    parts.append(("블리츠", abs(math.log(max(0.05, d.blitz))) * 0.6))
    parts.append(("맨/존", abs(d.man_zone) * 0.4))
    parts.append(("박스", abs(d.box) * 0.3))
    for key, v in t.situational.items():
        parts.append((f"상황 {key}", abs(v.get("pass", 0.0)) * 1.0 + abs(math.log(max(0.05, v.get("blitz", 1.0)))) * 0.3))
    raw = sum(v for _, v in parts) * BREAK_RELIEF.get(t.predictability.tendency_break, 1.0)
    if t.predictability.personnel_mix:
        raw *= 0.92
    expo = 100 * (1 - math.exp(-raw / 1.6))
    warns = [f"{label}: 리그 평균과 차이가 커서 상대가 빨리 읽습니다" for label, v in parts if v >= 0.45]
    return round(expo, 1), warns


def call_mix(t: Tactics) -> dict:
    """대표 콜 비율 요약 (표시용)."""
    p = min(0.95, max(0.05, 1 - t.offense.run_share)) if t.offense.run_share is not None else LEAGUE_PASS_RATE
    cov = t.defense.coverage or {}
    tot = sum(cov.values()) or 1
    man = sum(v for k, v in cov.items() if k in MAN_COVERS) / tot if cov else None
    return {"pass": p, "man": man}


def simulate_compare(league, abbr: str, new: Tactics, opponent: str, n: int = 16) -> dict:
    """같은 시드로 현재 전술 vs 새 전술 (다음 상대, 홈/원정 번갈아). 호출자는 리그 잠금을 잡고 있어야 한다."""
    from ..domain.models import ScheduledGame
    from ..engine.api import simulate
    team = league.teams[abbr]
    old = team.tactics
    res = {}
    try:
        for label, tac in (("current", old), ("new", new)):
            team.tactics = tac
            pf = pa = wins = 0.0
            for i in range(n):
                home, away = (abbr, opponent) if i % 2 == 0 else (opponent, abbr)
                g = ScheduledGame(f"preview_{i}", league.season, 0, "REG", home, away, gameday=league.season_start())
                out = simulate(league, g, seed=zlib.crc32(f"preview:{abbr}:{opponent}:{i}".encode()),
                               play_by_play=False, injuries=False)
                me = out.home_score if home == abbr else out.away_score
                them = out.away_score if home == abbr else out.home_score
                pf, pa = pf + me, pa + them
                wins += 1.0 if me > them else 0.5 if me == them else 0.0
            res[label] = {"pf": pf / n, "pa": pa / n, "win": wins / n}
    finally:
        team.tactics = old
    res["diff_margin"] = (res["new"]["pf"] - res["new"]["pa"]) - (res["current"]["pf"] - res["current"]["pa"])
    res["n"] = n
    return res
