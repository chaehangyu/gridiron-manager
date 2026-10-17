"""스카우팅 파악도와 정보 공개 범위 (PRD F13, M5e).

사용자 팀 관점에서 선수별 파악도 0–100. 우리 선수 100, 다른 팀 선수는 명성(경력·주전 여부)으로 20–40에서 시작.
증가: 우리와 경기한 상대 선수 +20, 스카우트 배정 대상 +25/주(포지션 배정은 리그 전체라 +10), 매주 +1.
능력치 표시: 파악도 100이면 정확, 0이면 ±5. 범위 중심은 선수·능력치별 고정 오차라 볼 때마다 흔들리지 않는다.
숨김 능력치: 다른 팀 선수는 비공개, 우리 선수는 합류 4주 뒤 서술형으로 공개. AI 팀은 실제 능력치를 쓴다 (F13-9).
"""
from __future__ import annotations

import zlib

from ..domain.attributes import HIDDEN_KEYS, clamp, stars
from ..domain.models import League, Player, RosterStatus
from ..ratings.position_rating import position_rating

SCOUTS = 3
TARGETS = ("next_opponent", "free_agents")      # + "pos:<그룹>"
DEFAULT_ASSIGN = ["next_opponent", "next_opponent", "free_agents"]
HIDDEN_TEXT = {"durability": ("부상에 강함", "부상이 잦음"), "consistency": ("기복이 적음", "기복이 심함"),
               "big_games": ("큰 경기에 강함", "큰 경기에서 위축됨"), "recovery": ("회복이 빠름", "회복이 느림"),
               "pain_tolerance": ("통증을 잘 참음", "통증에 민감함")}


def base_knowledge(league: League, p: Player, observer: str) -> float:
    if p.team == observer:
        return 100.0
    starter = any(p.id in ids[:1] for t in league.teams.values() for ids in t.depth_chart.values())
    fame = min(1.0, p.years_exp / 8) * 0.5 + (0.5 if starter else 0.0)
    return round(20 + 20 * fame, 1)


def knowledge(league: League, p: Player, observer: str) -> float:
    if p.team == observer:
        return 100.0
    k = league.knowledge.get(p.id)
    return k if k is not None else base_knowledge(league, p, observer)


def _add(league: League, p: Player, observer: str, amt: float) -> None:
    league.knowledge[p.id] = min(100.0, knowledge(league, p, observer) + amt)


def _err(pid: str, key: str) -> float:
    """선수·능력치별 고정 오차 −1…1."""
    return zlib.crc32(f"{pid}:{key}".encode()) / 2**31 - 1.0


def attr_range(league: League, p: Player, key: str, observer: str) -> tuple[float, float] | None:
    """능력치 범위 (보이는 값). 숨김 능력치는 다른 팀 선수면 None."""
    k = knowledge(league, p, observer)
    v = p.attributes[key]
    if key in HIDDEN_KEYS and p.team != observer:
        return None
    hw = 5.0 * (1 - k / 100)
    if hw < 0.05:
        return v, v
    c = v + _err(p.id, key) * hw * 0.8
    return round(clamp(c - hw)), round(clamp(c + hw))


def value_range(league: League, p: Player, observer: str, value: float, key: str) -> tuple[float, float]:
    """종합 평가(PR·역할 평가) 범위: 파악도 0이면 ±3."""
    k = knowledge(league, p, observer)
    hw = 3.0 * (1 - k / 100)
    c = value + _err(p.id, key) * hw * 0.8
    return round(clamp(c - hw), 1), round(clamp(c + hw), 1)


def pr_range(league: League, p: Player, observer: str, position=None) -> tuple[float, float]:
    pos = position or p.position
    return value_range(league, p, observer, position_rating(p, pos), f"PR:{pos.value}")


def fmt_range(lo: float, hi: float) -> str:
    return f"{lo:.1f}" if lo == hi else f"{lo:.1f}–{hi:.1f}"


def star_text(lo: float, hi: float) -> str:
    a, b = stars(lo), stars(hi)
    fmt = lambda s: "★" * int(s) + ("½" if s % 1 else "")  # noqa: E731
    return fmt(a) if a == b else f"{fmt(a)}–{fmt(b)}"


def hidden_comments(p: Player, weeks_with_team: int) -> list[str]:
    """우리 선수 숨김 능력치: 4주 뒤 코치·의료진 코멘트 (F13-6)."""
    if weeks_with_team < 4:
        return ["(코치진이 아직 파악 중 — 4주 후 공개)"]
    out = []
    for key, (good, bad) in HIDDEN_TEXT.items():
        v = p.attributes.get(key, 10.5)
        if v >= 14:
            out.append(good)
        elif v <= 7:
            out.append(bad)
    return out or ["특이 사항 없음"]


def next_opponent(league: League, team: str, week: int) -> str | None:
    for g in sorted(league.schedule, key=lambda g: g.week):
        if g.week >= week and not g.played and team in (g.home, g.away):
            return g.away if g.home == team else g.home
    return None


def weekly_update(league: League, observer: str, week: int) -> None:
    """주 마감: 경기한 상대 +20, 스카우트 배정 +25(포지션 +10), 전체 +1."""
    from ..season.roster import GROUP_OF
    for g in league.games_in_week(week):
        if observer in (g.home, g.away) and g.played:
            opp = g.away if g.home == observer else g.home
            for p in league.roster(opp, (RosterStatus.ACTIVE,)):
                _add(league, p, observer, 20)
    nxt = next_opponent(league, observer, week + 1)
    for target in (league.scout_assignments or DEFAULT_ASSIGN)[:SCOUTS]:
        if target == "next_opponent" and nxt:
            for p in league.roster(nxt, (RosterStatus.ACTIVE, RosterStatus.PRACTICE_SQUAD)):
                _add(league, p, observer, 25)
        elif target == "free_agents":
            for p in sorted(league.free_agents(), key=position_rating, reverse=True)[:60]:
                _add(league, p, observer, 25)
        elif target.startswith("pos:"):
            grp = target[4:]
            for p in league.players.values():
                if p.team != observer and GROUP_OF.get(p.position) == grp and p.roster_status != RosterStatus.RETIRED:
                    _add(league, p, observer, 10)
    for pid, k in list(league.knowledge.items()):
        league.knowledge[pid] = min(100.0, k + 1)
