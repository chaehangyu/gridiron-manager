"""선수 능력치 (1–20, PRD F2-2 · F2-5).

- 모든 능력치는 **높을수록 좋다** (숨김 능력치 포함).
- 절대 척도: 포지션과 무관하게 리그 전체 기준 하나.
- 내부 값은 1.0–20.0 실수, 화면 표기는 정수.
"""
from __future__ import annotations

from dataclasses import dataclass

ATTR_MIN = 1.0
ATTR_MAX = 20.0


@dataclass(frozen=True)
class AttrDef:
    key: str
    label_ko: str
    group: str
    hidden: bool = False


_DEFS = [
    # 신체
    AttrDef("speed", "스피드", "physical"),
    AttrDef("acceleration", "가속", "physical"),
    AttrDef("agility", "민첩성", "physical"),
    AttrDef("strength", "근력", "physical"),
    AttrDef("jumping", "점프", "physical"),
    AttrDef("stamina", "지구력", "physical"),
    # 정신
    AttrDef("football_iq", "풋볼 IQ", "mental"),
    AttrDef("composure", "침착성", "mental"),
    AttrDef("determination", "결단력", "mental"),
    AttrDef("leadership", "리더십", "mental"),
    AttrDef("consistency", "일관성", "mental", hidden=True),
    AttrDef("big_games", "큰경기 강도", "mental", hidden=True),
    # 의료 (숨김)
    AttrDef("durability", "내구성", "medical", hidden=True),
    AttrDef("recovery", "회복력", "medical", hidden=True),
    AttrDef("pain_tolerance", "통증 내성", "medical", hidden=True),
    # 패싱
    AttrDef("throw_power", "송구 파워", "passing"),
    AttrDef("short_accuracy", "단거리 정확도", "passing"),
    AttrDef("medium_accuracy", "중거리 정확도", "passing"),
    AttrDef("deep_accuracy", "장거리 정확도", "passing"),
    AttrDef("throw_on_run", "이동 중 송구", "passing"),
    AttrDef("pocket_presence", "포켓 감각", "passing"),
    AttrDef("decision", "판단력", "passing"),
    # 볼 캐리
    AttrDef("ball_security", "볼 안전성", "ball_carrier"),
    AttrDef("vision", "시야", "ball_carrier"),
    AttrDef("elusiveness", "회피", "ball_carrier"),
    AttrDef("break_tackle", "태클 돌파", "ball_carrier"),
    # 리시빙
    AttrDef("catching", "캐칭", "receiving"),
    AttrDef("contested_catch", "경합 캐치", "receiving"),
    AttrDef("route_running", "루트 러닝", "receiving"),
    AttrDef("release", "릴리즈", "receiving"),
    # 블로킹
    AttrDef("run_block", "런 블록", "blocking"),
    AttrDef("pass_block", "패스 블록", "blocking"),
    AttrDef("lead_block", "리드 블록", "blocking"),
    # 수비
    AttrDef("power_rush", "패스 러시(파워)", "defense"),
    AttrDef("finesse_rush", "패스 러시(피네스)", "defense"),
    AttrDef("block_shedding", "블록 떨치기", "defense"),
    AttrDef("run_stop", "런 스톱", "defense"),
    AttrDef("tackling", "태클", "defense"),
    AttrDef("pursuit", "추격", "defense"),
    AttrDef("man_coverage", "맨 커버리지", "defense"),
    AttrDef("zone_coverage", "존 커버리지", "defense"),
    AttrDef("press", "프레스", "defense"),
    AttrDef("ball_skills", "볼 스킬", "defense"),
    # 스페셜
    AttrDef("kick_power", "킥 파워", "special"),
    AttrDef("kick_accuracy", "킥 정확도", "special"),
    AttrDef("punt_power", "펀트 파워", "special"),
    AttrDef("punt_accuracy", "펀트 정확도", "special"),
    AttrDef("returning", "리턴", "special"),
]

ATTRIBUTES: dict[str, AttrDef] = {d.key: d for d in _DEFS}
ATTR_KEYS: list[str] = [d.key for d in _DEFS]
VISIBLE_KEYS: list[str] = [d.key for d in _DEFS if not d.hidden]
HIDDEN_KEYS: list[str] = [d.key for d in _DEFS if d.hidden]


def clamp(value: float) -> float:
    return max(ATTR_MIN, min(ATTR_MAX, value))


# F2-5a 등급 정의
_GRADES = [
    (20, "역대급"),
    (18, "올프로"),
    (16, "프로볼"),
    (14, "우수 주전"),
    (12, "평균 주전"),
    (10, "로테이션"),
    (8, "백업"),
    (6, "로스터 끝자리"),
    (4, "NFL 미달"),
    (1, "사실상 없음"),
]


def grade_label(value: float) -> str:
    v = round(value)
    for floor, label in _GRADES:
        if v >= floor:
            return label
    return _GRADES[-1][1]


# F2-5c 포지션 평가(PR) → 별점
_STARS = [(17.0, 5.0), (15.5, 4.5), (14.0, 4.0), (12.5, 3.5), (11.0, 3.0), (9.5, 2.5), (8.0, 2.0), (6.5, 1.5)]


def stars(pr: float) -> float:
    for floor, s in _STARS:
        if pr >= floor:
            return s
    return 1.0


def to_hundred(value: float) -> float:
    """1–20 → 0–100 (엔진 골격 변환용)."""
    return (clamp(value) - ATTR_MIN) / (ATTR_MAX - ATTR_MIN) * 100.0
