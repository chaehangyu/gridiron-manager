"""전술 숙련도 (PRD F11-3, ENGINE_DESIGN §4.4) — 팀 단위, 영역별 0–100.

- 효과: 콜이 속한 영역의 숙련도로 그 콜에 쓰이는 능력치를 곱한다.
  설계식 `m = 0.92 + 0.08·F/100`을 게임 시작 기본값(80)에서 1이 되도록 나눈다 → F 0: −6.5%, 80: 0, 100: +1.6%.
  기본값이 1이라 실측 기준 분포의 보정(중심값)이 그대로 유지된다.
- 정신적 실수: 숙련도가 80보다 낮으면 반칙·커버리지 붕괴 확률이 오른다.
- 시작값(F11-3e): 2025 실측 사용 비율이 리그 평균이면 80, 절반이면 약 63, 거의 안 썼으면 40.
- 증감(F11-3c): 경기에서 해당 영역 비중 20% 이상이면 +2, 5% 미만이면 주당 −1. 훈련 초점은 §training.
"""
from __future__ import annotations

import math

DOMAINS = ("run_zone", "run_gap", "pass_quick", "pass_inter", "pass_deep", "pass_pa", "pass_screen",
           "front_43", "front_34", "cov_man", "cov_zone", "blitz", "special")
LABELS = {"run_zone": "런: 존", "run_gap": "런: 갭/파워", "pass_quick": "패스: 퀵", "pass_inter": "패스: 인터미디어트",
          "pass_deep": "패스: 딥", "pass_pa": "플레이액션", "pass_screen": "스크린", "front_43": "프론트 4-3",
          "front_34": "프론트 3-4", "cov_man": "맨 커버리지", "cov_zone": "존 커버리지", "blitz": "블리츠 패키지",
          "special": "특수팀"}
BASE = 80.0


def multiplier(f: float) -> float:
    return (0.92 + 0.08 * f / 100) / (0.92 + 0.08 * BASE / 100)


def mistake_factor(f: float) -> float:
    """반칙·커버리지 붕괴 배율: 80 이상이면 1, 40이면 1.6."""
    return 1.0 + 1.5 * max(0.0, (BASE - f) / 100)


def default() -> dict[str, float]:
    return {d: BASE for d in DOMAINS}


def initial(front: str, team_tend: dict | None, league_tend: dict | None) -> dict[str, float]:
    """실측 성향으로 정한 게임 시작 숙련도."""
    out = default()
    out["front_43" if front == "4-3" else "front_34"] = 88.0
    out["front_34" if front == "4-3" else "front_43"] = 45.0
    if not team_tend or not league_tend:
        return out
    to, lo = team_tend["offense"], league_tend["offense"]
    td, ld = team_tend["defense"], league_tend["defense"]

    def from_ratio(u: float) -> float:
        return round(min(92.0, max(40.0, BASE + 25 * math.log(max(u, 1e-3)))), 1)

    out["run_zone"] = from_ratio(to["outside_run"] / lo["outside_run"])
    out["run_gap"] = from_ratio((1 - to["outside_run"]) / (1 - lo["outside_run"]))
    out["pass_deep"] = from_ratio(to["deep_rate"] / lo["deep_rate"])
    out["pass_pa"] = from_ratio(to["pa_rate"] / lo["pa_rate"])
    out["pass_screen"] = from_ratio(to["screen_rate"] / lo["screen_rate"])
    out["cov_man"] = from_ratio(td["man_rate"] / ld["man_rate"])
    out["cov_zone"] = from_ratio((1 - td["man_rate"]) / (1 - ld["man_rate"]))
    out["blitz"] = from_ratio(td["blitz_rate"] / ld["blitz_rate"])
    return out


# 영역 사용 비중을 잴 때의 분모 묶음
GROUPS = {"run": ("run_zone", "run_gap"), "pass": ("pass_quick", "pass_inter", "pass_deep", "pass_screen"),
          "pa": ("pass_pa",), "cov": ("cov_man", "cov_zone"), "blitz": ("blitz",), "front": ("front_43", "front_34")}


def after_game(fam: dict[str, float], usage: dict[str, float]) -> dict[str, float]:
    """경기 후: 비중 20% 이상 영역 +2 (특수팀은 매 경기 사용)."""
    out = dict(fam)
    shares = usage_shares(usage)
    for d, s in shares.items():
        if s >= 0.20:
            out[d] = min(100.0, out[d] + 2.0)
    out["special"] = min(100.0, out["special"] + 2.0)
    return out


def weekly_decay(fam: dict[str, float], season_usage: dict[str, float]) -> dict[str, float]:
    """주 단위: 최근 비중 5% 미만 영역 −1."""
    out = dict(fam)
    for d, s in usage_shares(season_usage).items():
        if s < 0.05:
            out[d] = max(0.0, out[d] - 1.0)
    return out


def usage_shares(usage: dict[str, float]) -> dict[str, float]:
    shares = {}
    for group, doms in GROUPS.items():
        if group == "pa":
            n = usage.get("pass_total", 0.0)
            shares["pass_pa"] = usage.get("pass_pa", 0.0) / n if n else 0.0
            continue
        if group == "blitz":
            n = usage.get("def_pass_total", 0.0)
            shares["blitz"] = usage.get("blitz", 0.0) / n if n else 0.0
            continue
        tot = sum(usage.get(d, 0.0) for d in doms)
        for d in doms:
            shares[d] = usage.get(d, 0.0) / tot if tot else 0.0
    return shares
