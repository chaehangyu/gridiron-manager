"""4th down·2점 전환 판단 (nfl4th 방식, ENGINE_DESIGN §5 · PRD F5-6).

nfl4th와 같은 구조로, 각 선택지 이후 상태의 승률(WP)을 비교한다.
- FG: 성공 확률 × WP(3점 추가 후 상대 킥오프) + 실패 × WP(상대 공격, 킥 지점+7야드, 최소 자기 20야드)
- 펀트: 실측 평균 순 거리 이후 상대 공격
- 공격: 실측 전환율(남은 거리별) × WP(1st down) + 실패 × WP(상대 공격, 그 자리)
실측 표와 WP·EP 모델은 gridiron.baseline에서 만든다.
"""
from __future__ import annotations

from functools import lru_cache
from statistics import mean
from typing import TYPE_CHECKING

from ...baseline.tables import tables
from ...config import load
from .. import models_ml as M

if TYPE_CHECKING:
    from ..skeleton.game import GameSim


@lru_cache(maxsize=1)
def _cfg() -> dict:
    return load("engine")["decisions"]


@lru_cache(maxsize=1)
def _punt_net() -> dict[str, float]:
    rows = tables()["special"]["punt_rows"]
    return {b: mean(r[0] - r[2] for r in rs) for b, rs in rows.items()}


def punt_bucket(yardline_100: float) -> str:
    for limit, key in ((40, "40"), (50, "50"), (60, "60"), (70, "70")):
        if yardline_100 <= limit:
            return key
    return "99"


def fg_base_prob(distance: float, indoor: bool) -> float:
    tb = tables()["special"]
    d = int(round(min(max(distance, 18), 70)))
    p = tb["fg_make_by_yard"][str(d)]
    if indoor:
        p = min(0.995, p + tb["fg_indoor_bonus"])
    return p


def conversion_prob(togo: float) -> float:
    t = int(min(max(round(togo), 1), 15))
    return tables()["special"]["conversion_by_togo"][str(t)]


def clock_state(g: "GameSim") -> tuple[float, float]:
    """(경기 남은 초, 전·후반 남은 초). 연장은 정규시간 종료로 본다."""
    quarter = len(g.team[0].stat["ptsQtrs"])
    q_sec = g.clock * 60
    if quarter > g.num_periods:
        return q_sec, q_sec
    game_sec = (g.num_periods - quarter) * g.settings.quarter_length * 60 + q_sec
    half_sec = q_sec + (g.settings.quarter_length * 60 if quarter in (1, 3) else 0)
    return game_sec, half_sec


def wp_for(g: "GameSim", team: int, score_diff: float, down: int, togo: float, yardline_100: float,
           seconds_used: float = 0.0) -> float:
    game_sec, half_sec = clock_state(g)
    game_sec = max(0.0, game_sec - seconds_used)
    half_sec = max(0.0, half_sec - seconds_used)
    other = 1 - team
    e = M.ep(down, togo, yardline_100)
    return M.wp(score_diff, game_sec, half_sec, e, g.timeouts[team], g.timeouts[other], home=team == 0)


def wp_after_score(g: "GameSim", team: int, new_diff: float, seconds_used: float = 5.0) -> float:
    """우리가 득점한 뒤 상대가 킥오프를 받는 상태에서 우리 팀 승률."""
    start = _cfg()["expected_kickoff_start"]
    return 1 - wp_for(g, 1 - team, -new_diff, 1, 10, 100 - start, seconds_used)


def fourth_down_options(g: "GameSim", kicker_prob) -> dict[str, float]:
    o = g.o
    yl = 100 - g.scrimmage
    togo = g.toGo
    diff = g.team[o].stat["pts"] - g.team[1 - o].stat["pts"]
    out: dict[str, float] = {}

    # 공격
    p_conv = conversion_prob(togo)
    if yl - togo <= 0:
        wp_success = wp_after_score(g, o, diff + 7)
    else:
        new_yl = max(1, yl - togo - 3)
        wp_success = wp_for(g, o, diff, 1, min(10, new_yl), new_yl, 6)
    wp_fail = 1 - wp_for(g, 1 - o, -diff, 1, 10, 100 - min(99, yl + 1), 6)
    out["go"] = p_conv * wp_success + (1 - p_conv) * wp_fail

    # FG
    distance = yl + 17
    if distance <= _cfg()["fg_max_distance"]:
        p_make = kicker_prob
        wp_make = wp_after_score(g, o, diff + 3)
        miss_spot = max(20, 100 - (yl + 7))  # 상대 기준 자기 진영 위치
        wp_miss = 1 - wp_for(g, 1 - o, -diff, 1, 10, 100 - miss_spot, 5)
        out["fieldGoal"] = p_make * wp_make + (1 - p_make) * wp_miss

    # 펀트
    if yl > 35:
        net = _punt_net()[punt_bucket(yl)]
        landing = yl - net
        opp_yl = 80 if landing <= 0 else 100 - landing
        out["punt"] = 1 - wp_for(g, 1 - o, -diff, 1, 10, min(99, max(1, opp_yl)), 8)
    return out


def fourth_down_choice(g: "GameSim", kicker_prob: float) -> str:
    opts = fourth_down_options(g, kicker_prob)
    margin = _cfg()["fourth_down_go_margin"]
    # 장거리 FG는 실제 감독이 승률 최적보다 덜 시도한다
    if "fieldGoal" in opts and 100 - g.scrimmage + 17 >= 50:
        opts["fieldGoal"] -= _cfg()["fg_long_margin"]
    best_kick = max((v, k) for k, v in opts.items() if k != "go") if len(opts) > 1 else None
    if best_kick is None:
        return "go"
    # 승률이 0·1에 가까우면 선택지 간 차이가 작아지므로, 보수성 여유도 비례해서 줄인다
    p = max(opts.values())
    scaled = margin * 4 * p * (1 - p)
    return "go" if opts["go"] > best_kick[0] + scaled else best_kick[1]


def two_point_choice(g: "GameSim", p_xp: float, p_two: float) -> bool:
    o = g.o
    diff = g.team[o].stat["pts"] - g.team[1 - o].stat["pts"]
    ev_xp = p_xp * wp_after_score(g, o, diff + 1) + (1 - p_xp) * wp_after_score(g, o, diff)
    ev_two = p_two * wp_after_score(g, o, diff + 2) + (1 - p_two) * wp_after_score(g, o, diff)
    return ev_two > ev_xp + _cfg()["two_point_margin"]


def home_win_probability(g: "GameSim") -> float:
    o = g.o
    yl = 100 - g.scrimmage
    if g.awaitingKickoff is not None or g.awaitingAfterTouchdown or not (0 < yl < 100):
        diff_home = g.team[0].stat["pts"] - g.team[1].stat["pts"]
        receiving = 1 - g.awaitingKickoff if g.awaitingKickoff is not None else 1 - o
        w = wp_for(g, receiving, diff_home if receiving == 0 else -diff_home, 1, 10, 100 - _cfg()["expected_kickoff_start"])
        return w if receiving == 0 else 1 - w
    diff = g.team[o].stat["pts"] - g.team[1 - o].stat["pts"]
    w = wp_for(g, o, diff, g.down, g.toGo, yl)
    return w if o == 0 else 1 - w
