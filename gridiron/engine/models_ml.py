"""기대득점(EP)·승률(WP)·기대 패스 확률(xpass) 추론 (순수 Python). 학습: gridiron.baseline.train_models."""
from __future__ import annotations

import json
import math
from functools import lru_cache

from ..config import DATA_DIR


@lru_cache(maxsize=1)
def _models() -> dict:
    return json.loads((DATA_DIR / "baseline" / "models.json").read_text(encoding="utf-8"))


def ep(down: int, togo: float, yardline_100: float) -> float:
    """공격 팀 기준 기대득점. yardline_100 = 상대 엔드존까지 거리."""
    g = _models()["ep_grid"]
    d = min(max(int(down), 1), 4) - 1
    t = min(max(int(round(togo)), 1), 30) - 1
    y = min(max(int(round(yardline_100)), 1), 99) - 1
    return g[d][t][y]


def _logistic(name: str, feats: dict[str, float]) -> float:
    m = _models()[name]
    x = m["intercept"] + sum(c * feats[f] for f, c in zip(m["features"], m["coef"]))
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


def wp(score_diff: float, game_seconds_remaining: float, half_seconds_remaining: float, ep_value: float,
       pos_timeouts: int, def_timeouts: int, home: bool) -> float:
    """공격 팀 승리 확률."""
    elapsed = (3600 - min(max(game_seconds_remaining, 0), 3600)) / 3600
    feats = {
        "score_diff": score_diff,
        "diff_time_ratio": score_diff * math.exp(4 * elapsed),
        "ep": ep_value,
        "ep_x_elapsed": ep_value * elapsed,
        "game_sec": game_seconds_remaining / 3600,
        "half_sec": half_seconds_remaining / 1800,
        "pos_to": pos_timeouts,
        "def_to": def_timeouts,
        "home": 1.0 if home else 0.0,
        "score_diff_x_late": score_diff * (1.0 if elapsed > 0.9 else 0.0),
        "diff_sqrt": score_diff / math.sqrt(min(max(game_seconds_remaining, 0), 3600) / 3600 + 0.01),
        "ep_sqrt": ep_value / math.sqrt(min(max(game_seconds_remaining, 0), 3600) / 3600 + 0.01),
        "to_diff_late": (pos_timeouts - def_timeouts) * (1.0 if elapsed > 0.9 else 0.0),
    }
    return _logistic("wp", feats)


def xpass(down: int, togo: float, yardline_100: float, score_diff: float, game_seconds_remaining: float,
          half_seconds_remaining: float, wp_value: float) -> float:
    togo = min(max(togo, 1), 30)
    lt = math.log(togo)
    late = 1.0 if game_seconds_remaining < 900 else 0.0
    sd = max(-28, min(28, score_diff)) / 10
    feats = {
        "d2": 1.0 if down == 2 else 0.0, "d3": 1.0 if down == 3 else 0.0, "d4": 1.0 if down == 4 else 0.0,
        "log_togo": lt, "togo_d3": lt * (down == 3), "togo_d4": lt * (down == 4),
        "yl": yardline_100 / 100, "yl2": (yardline_100 / 100) ** 2,
        "goal": 1.0 if yardline_100 <= togo else 0.0,
        "score_diff": sd, "score_diff_late": sd * late,
        "trail_late": 1.0 if (score_diff < 0 and game_seconds_remaining < 300) else 0.0,
        "lead_late": 1.0 if (score_diff > 0 and game_seconds_remaining < 300) else 0.0,
        "half_sec": half_seconds_remaining / 1800, "two_min": 1.0 if half_seconds_remaining <= 120 else 0.0,
        "wp": wp_value, "wp2": wp_value ** 2,
    }
    return _logistic("xpass", feats)
