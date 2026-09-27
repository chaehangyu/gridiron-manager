"""기대득점(EP)·승률(WP)·기대 패스 확률(xpass) 경량 모델 학습 (ENGINE_DESIGN §5, F5-6).

nflfastR 모델 구조를 참고해, 게임 실행 중 순수 Python으로 빠르게 계산할 수 있는 형태로 다시 학습한다.
- EP: nflverse `ep`를 목표로 부스팅 회귀 → (다운, 남은 거리, 필드 위치) 격자 표로 저장
- WP: 실제 경기 결과를 목표로 로지스틱 회귀 (nflfastR WP 특징값 사용)
- xpass: 실제 패스 여부를 목표로 로지스틱 회귀

    python -m gridiron.baseline.train_models --cache data/raw
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from .build import PBP_SEASONS, fetch

COLS = ["game_id", "season", "season_type", "play_type", "posteam", "home_team", "down", "ydstogo", "yardline_100",
        "half_seconds_remaining", "game_seconds_remaining", "game_half", "qtr", "score_differential",
        "posteam_timeouts_remaining", "defteam_timeouts_remaining", "ep", "wp", "xpass", "qb_dropback",
        "qb_kneel", "qb_spike", "two_point_attempt", "result", "goal_to_go"]


def load(cache: Path) -> pd.DataFrame:
    frames = []
    for y in PBP_SEASONS:
        df = pd.read_parquet(fetch(cache, f"pbp/play_by_play_{y}.parquet"))
        frames.append(df[[c for c in COLS if c in df.columns]])
    d = pd.concat(frames, ignore_index=True)
    d = d[d.season_type == "REG"]
    return d


# ── WP 특징값 (게임 실행 코드와 같은 정의를 써야 한다: gridiron.engine.models_ml.wp_features) ──
WP_FEATURES = ["score_diff", "diff_time_ratio", "ep", "ep_x_elapsed", "game_sec", "half_sec", "pos_to", "def_to",
               "home", "score_diff_x_late", "diff_sqrt", "ep_sqrt", "to_diff_late"]


def wp_frame(d: pd.DataFrame) -> pd.DataFrame:
    elapsed = (3600 - d.game_seconds_remaining.clip(0, 3600)) / 3600
    f = pd.DataFrame({
        "score_diff": d.score_differential,
        "diff_time_ratio": d.score_differential * np.exp(4 * elapsed),
        "ep": d.ep,
        "ep_x_elapsed": d.ep * elapsed,
        "game_sec": d.game_seconds_remaining / 3600,
        "half_sec": d.half_seconds_remaining / 1800,
        "pos_to": d.posteam_timeouts_remaining,
        "def_to": d.defteam_timeouts_remaining,
        "home": (d.posteam == d.home_team).astype(int),
        "score_diff_x_late": d.score_differential * (elapsed > 0.9),
        # 막판 표현력: 남은 시간의 제곱근으로 나눈 점수 차·기대득점 (정규분포형 승률 모델의 핵심 항)
        "diff_sqrt": d.score_differential / np.sqrt(d.game_seconds_remaining.clip(0, 3600) / 3600 + 0.01),
        "ep_sqrt": d.ep / np.sqrt(d.game_seconds_remaining.clip(0, 3600) / 3600 + 0.01),
        "to_diff_late": (d.posteam_timeouts_remaining - d.defteam_timeouts_remaining) * (elapsed > 0.9),
    })
    return f


XPASS_FEATURES = ["d2", "d3", "d4", "log_togo", "togo_d3", "togo_d4", "yl", "yl2", "goal", "score_diff",
                  "score_diff_late", "trail_late", "lead_late", "half_sec", "two_min", "wp", "wp2"]


def xpass_frame(d: pd.DataFrame) -> pd.DataFrame:
    late = (d.game_seconds_remaining < 900).astype(int)
    togo = d.ydstogo.clip(1, 30)
    return pd.DataFrame({
        "d2": (d.down == 2).astype(int), "d3": (d.down == 3).astype(int), "d4": (d.down == 4).astype(int),
        "log_togo": np.log(togo), "togo_d3": np.log(togo) * (d.down == 3), "togo_d4": np.log(togo) * (d.down == 4),
        "yl": d.yardline_100 / 100, "yl2": (d.yardline_100 / 100) ** 2, "goal": d.goal_to_go.fillna(0),
        "score_diff": d.score_differential.clip(-28, 28) / 10,
        "score_diff_late": d.score_differential.clip(-28, 28) / 10 * late,
        "trail_late": ((d.score_differential < 0) & (d.game_seconds_remaining < 300)).astype(int),
        "lead_late": ((d.score_differential > 0) & (d.game_seconds_remaining < 300)).astype(int),
        "half_sec": d.half_seconds_remaining / 1800, "two_min": (d.half_seconds_remaining <= 120).astype(int),
        "wp": d.wp, "wp2": d.wp ** 2,
    })


def train(cache: Path) -> dict:
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    d = load(cache)
    out: dict = {"seasons": PBP_SEASONS}

    # ── EP 격자 ──
    e = d[d.down.notna() & d.ep.notna() & d.play_type.isin(["pass", "run", "punt", "field_goal"])]
    e = e[e.half_seconds_remaining > 120]
    Xe = np.column_stack([e.down, e.ydstogo.clip(1, 30), e.yardline_100])
    gbr = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.08, max_leaf_nodes=48).fit(Xe, e.ep)
    grid = []
    for down in range(1, 5):
        rows = []
        for togo in range(1, 31):
            xs = np.column_stack([np.full(99, down), np.full(99, togo), np.arange(1, 100)])
            rows.append([round(float(v), 3) for v in gbr.predict(xs)])
        grid.append(rows)
    out["ep_grid"] = grid  # [down-1][togo-1][yardline_100-1]
    ep_mae = float(np.mean(np.abs(gbr.predict(Xe) - e.ep)))
    out["ep_mae_vs_nflverse"] = round(ep_mae, 4)

    # ── WP (실제 결과) ──
    w = d[d.down.notna() & d.ep.notna() & d.result.notna() & d.posteam.notna() & (d.result != 0)].copy()
    w["won"] = np.where(w.posteam == w.home_team, w.result > 0, w.result < 0).astype(int)
    Xw = wp_frame(w)[WP_FEATURES].to_numpy()
    lr = LogisticRegression(C=1.0, max_iter=2000).fit(Xw, w.won)
    pw = lr.predict_proba(Xw)[:, 1]
    out["wp"] = {"features": WP_FEATURES, "intercept": float(lr.intercept_[0]),
                 "coef": [float(c) for c in lr.coef_[0]],
                 "brier": round(float(brier_score_loss(w.won, pw)), 4),
                 "brier_nflverse": round(float(brier_score_loss(w.won, w.wp.clip(0, 1).fillna(0.5))), 4),
                 "mae_vs_nflverse": round(float(np.nanmean(np.abs(pw - w.wp))), 4)}

    # ── xpass (실제 패스 여부) ──
    x = d[d.play_type.isin(["pass", "run"]) & d.down.notna() & (d.qb_kneel != 1) & (d.qb_spike != 1)
          & (d.two_point_attempt != 1) & d.wp.notna()].copy()
    Xx = xpass_frame(x)[XPASS_FEATURES].to_numpy()
    yx = (x.qb_dropback == 1).astype(int)
    lx = LogisticRegression(C=1.0, max_iter=3000).fit(Xx, yx)
    px = lx.predict_proba(Xx)[:, 1]
    out["xpass"] = {"features": XPASS_FEATURES, "intercept": float(lx.intercept_[0]),
                    "coef": [float(c) for c in lx.coef_[0]],
                    "auc": round(float(roc_auc_score(yx, px)), 4),
                    "auc_nflverse": round(float(roc_auc_score(yx[x.xpass.notna()], x.xpass.dropna())), 4),
                    "logloss": round(float(log_loss(yx, px)), 4)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=DATA_DIR / "raw")
    ap.add_argument("--out", type=Path, default=DATA_DIR / "baseline" / "models.json")
    args = ap.parse_args()
    models = train(args.cache)
    args.out.write_text(json.dumps(models, separators=(",", ":")), encoding="utf-8")
    print(f"저장: {args.out} ({args.out.stat().st_size / 1024:.0f} KB)")
    print("EP MAE (nflverse 대비):", models["ep_mae_vs_nflverse"])
    print("WP Brier:", models["wp"]["brier"], "nflverse:", models["wp"]["brier_nflverse"],
          "MAE vs nflverse:", models["wp"]["mae_vs_nflverse"])
    print("xpass AUC:", models["xpass"]["auc"], "nflverse:", models["xpass"]["auc_nflverse"])


if __name__ == "__main__":
    main()
