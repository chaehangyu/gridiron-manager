"""신체 능력치: 컴바인 측정값 ↔ F2-5b 앵커 (절대 척도).

- 측정값이 없는 선수는 같은 포지션의 키·몸무게 회귀로 채우되, 컴바인에서 측정하지 않은(또는 초대받지 못한)
  선수가 평균보다 느린 경향을 반영해 잔차 표준편차의 0.3배만큼 불리하게 둔다.
- 나이: 28세 이후 스피드·가속·민첩성은 해마다 조금씩 떨어진다.
- 앵커 재계산(PRD Q13): 활동 선수 중 19.5 이상이 4명 이상 나오면 상단을 압축하고, 그 결과 앵커 표를 보고서에 남긴다.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

RATING_LEVELS = [20, 18, 16, 14, 12, 10, 8, 6, 4, 1]
ANCHORS = {  # F2-5b (+ 넓이뛰기·셔틀은 같은 원리로 추가)
    "forty": [4.28, 4.36, 4.44, 4.52, 4.62, 4.75, 4.90, 5.05, 5.20, 5.40],
    "bench": [40, 35, 31, 27, 23, 20, 16, 12, 8, 4],
    "vertical": [43, 40, 37, 35, 32, 30, 27, 25, 23, 20],
    "cone": [6.55, 6.70, 6.85, 7.00, 7.15, 7.35, 7.55, 7.75, 7.95, 8.20],
    "broad_jump": [134, 128, 124, 120, 116, 112, 107, 102, 97, 90],
    "shuttle": [3.95, 4.05, 4.13, 4.22, 4.32, 4.43, 4.55, 4.68, 4.80, 5.00],
}
LOWER_IS_BETTER = {"forty", "cone", "shuttle"}
MEASURES = list(ANCHORS)


def to_rating(measure: str, values: np.ndarray) -> np.ndarray:
    xs = np.array(ANCHORS[measure], dtype=float)
    ys = np.array(RATING_LEVELS, dtype=float)
    if measure in LOWER_IS_BETTER:  # np.interp는 x 오름차순이 필요
        return np.interp(values, xs, ys, left=20.0, right=1.0)
    return np.interp(values, xs[::-1], ys[::-1], left=1.0, right=20.0)


def from_rating(measure: str, rating: float) -> float:
    xs = np.array(ANCHORS[measure], dtype=float)
    ys = np.array(RATING_LEVELS, dtype=float)
    return float(np.interp(rating, ys[::-1], xs[::-1]))


def _height_in(ht) -> float | None:
    if isinstance(ht, str) and "-" in ht:
        f, i = ht.split("-")
        return int(f) * 12 + int(i)
    return None


def combine_measures(cache, roster: pd.DataFrame) -> pd.DataFrame:
    """roster(gsis_id, position, height_in, weight_lb, birth_date) → 측정값 표 (결측은 회귀로 채움) + measured 여부."""
    players = pd.read_parquet(cache / "players.parquet", columns=["gsis_id", "pfr_id", "display_name", "draft_year"])
    comb = pd.read_parquet(cache / "combine.parquet")
    by_pfr = comb[comb.pfr_id.notna()].drop_duplicates("pfr_id").set_index("pfr_id")
    m = roster[["gsis_id"]].merge(players[["gsis_id", "pfr_id", "display_name", "draft_year"]], on="gsis_id", how="left")
    found = m.pfr_id.map(lambda p: p in by_pfr.index if isinstance(p, str) else False)
    out = pd.DataFrame(index=roster.gsis_id)
    for k in MEASURES:
        out[k] = np.nan
    hit = m[found]
    for k in MEASURES:
        out.loc[hit.gsis_id.values, k] = by_pfr.loc[hit.pfr_id.values, k].values
    # pfr_id가 없으면 이름+시즌으로 한 번 더
    comb_name = comb.assign(key=comb.player_name.str.lower() + "|" + comb.season.astype(str)).drop_duplicates("key").set_index("key")
    miss = m[~found & m.display_name.notna() & m.draft_year.notna()]
    keys = miss.display_name.str.lower() + "|" + miss.draft_year.astype(int).astype(str)
    ok = keys.isin(comb_name.index)
    for k in MEASURES:
        out.loc[miss.gsis_id[ok].values, k] = comb_name.loc[keys[ok].values, k].values
    out = out.astype(float)
    measured = out.notna()

    # 결측 채우기: 포지션별 키·몸무게 회귀
    r = roster.set_index("gsis_id")
    hw = r[["height_in", "weight_lb"]].astype(float)
    hw = hw.fillna(hw.groupby(r.position).transform("median"))
    for k in MEASURES:
        for pos, idx in r.groupby("position").groups.items():
            y = out.loc[idx, k]
            X = np.column_stack([np.ones(len(idx)), hw.loc[idx].values])
            have = y.notna().values & np.isfinite(X).all(1)
            if have.sum() >= 8:
                beta, *_ = np.linalg.lstsq(X[have], y.values[have], rcond=None)
                pred = X @ beta
                sd = np.std(y.values[have] - pred[have])
            else:  # 표본이 적은 포지션(K·P·LS 등): 리그 전체 중앙값
                pred = np.full(len(idx), np.nanmedian(out[k].values))
                sd = np.nanstd(out[k].values)
            penalty = 0.3 * sd * (1 if k in LOWER_IS_BETTER else -1)
            fill = pred + penalty
            yy = y.values.copy()
            yy[~have] = fill[~have]
            out.loc[idx, k] = yy
    out.columns = MEASURES
    return out.join(measured.add_prefix("has_"))


def physical_ratings(meas: pd.DataFrame, roster: pd.DataFrame, season_start: date) -> tuple[pd.DataFrame, dict]:
    r = roster.set_index("gsis_id")
    rat = pd.DataFrame(index=meas.index)
    rat["speed"] = to_rating("forty", meas.forty.values)
    rat["strength"] = to_rating("bench", meas.bench.values)
    rat["jumping"] = 0.7 * to_rating("vertical", meas.vertical.values) + 0.3 * to_rating("broad_jump", meas.broad_jump.values)
    rat["agility"] = 0.6 * to_rating("cone", meas.cone.values) + 0.4 * to_rating("shuttle", meas.shuttle.values)
    # 가속: 10야드 구간 기록이 없어 넓이뛰기(폭발력)와 40야드를 섞는다
    rat["acceleration"] = 0.5 * to_rating("broad_jump", meas.broad_jump.values) + 0.5 * rat["speed"]
    # 나이
    bd = pd.to_datetime(r.birth_date, errors="coerce")
    age = ((pd.Timestamp(season_start) - bd).dt.days / 365.25).reindex(rat.index).fillna(26.0)
    decline = np.clip(age - 28, 0, None)
    for k, per_year in (("speed", 0.35), ("acceleration", 0.35), ("agility", 0.3), ("jumping", 0.3)):
        rat[k] = rat[k] - per_year * decline.values
    rat = rat.clip(1, 20)

    # 상단 재계산: 19.5 이상이 4명 이상이면 12 위쪽을 압축 (F2-5d "20은 0–3명")
    report = {}
    for k in rat.columns:
        v = rat[k].to_numpy(copy=True)
        third = np.sort(v)[-3] if len(v) >= 3 else 20
        factor = 1.0
        if third >= 19.5:
            factor = (19.4 - 12) / (third - 12)
            hi = v > 12
            v[hi] = 12 + (v[hi] - 12) * factor
            rat[k] = v
        report[k] = round(float(factor), 3)
    anchors = {}
    for k, measure in (("speed", "forty"), ("strength", "bench")):
        f = report[k]
        # 압축 후 각 등급에 해당하는 측정값 (12 이상만 영향)
        anchors[measure] = {lvl: round(from_rating(measure, 12 + (lvl - 12) / f if lvl > 12 else lvl), 2)
                            for lvl in RATING_LEVELS}
    return rat, {"top_compression": report, "recalibrated_anchors": anchors}
