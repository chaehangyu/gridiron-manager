"""명단 기반 릿지 회귀 (RAPM, PRD §7.2 "OL 패스·런 블록", "맨·존 커버리지").

플레이 결과 y를 그 플레이에 필드에 있던 공격 11명·수비 11명의 지표 변수와 상황 통제 변수로 회귀한다.
릿지 벌점이 표본이 적은 선수를 0(필드 평균)으로 당기므로, 계수 자체가 이미 수축된 개인 기여도다.

모델 세 개:
- pressure: 드롭백의 압박 여부 (공격 계수 음수 = 좋은 패스 블로커, 수비 계수 양수 = 좋은 패스 러셔)
- run: 디자인 런의 EPA (공격 양수 = 좋은 런 블로커, 수비 음수 = 좋은 런 수비)
- coverage: 드롭백 EPA, 수비수 변수를 맨/존 플레이로 나눔 (음수 = 좋은 커버리지)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import Ridge


def _design(of: pd.DataFrame, keys: np.ndarray, split_def_by: pd.Series | None = None):
    """keys 순서의 플레이에 대한 희소 설계 행렬과 열 이름."""
    row_of = pd.Series(np.arange(len(keys)), index=keys)
    o = of[of.key.isin(keys)].copy()
    o["row"] = o.key.map(row_of).values
    o["col"] = o.side + ":" + o.gsis_id
    if split_def_by is not None:
        is_def = o.side == "def"
        o.loc[is_def, "col"] = o.loc[is_def, "col"] + ":" + o.loc[is_def, "key"].map(split_def_by).values
    cols = pd.Index(sorted(o.col.unique()))
    X = sparse.csr_matrix((np.ones(len(o)), (o.row.values, cols.get_indexer(o.col))), shape=(len(keys), len(cols)))
    return X, cols


def _controls(d: pd.DataFrame, names: list[str]) -> sparse.csr_matrix:
    parts = []
    for n in names:
        dummies = pd.get_dummies(d[n].astype(str), prefix=n, drop_first=True, dtype=float)
        parts.append(sparse.csr_matrix(dummies.values))
    return sparse.hstack(parts).tocsr()


def _fit(X, y, w, alphas=(30, 100, 300, 1000, 3000)) -> tuple[np.ndarray, float]:
    """홀드아웃(20%)으로 벌점을 고른 뒤 전체로 다시 적합."""
    rng = np.random.default_rng(7)
    test = rng.random(X.shape[0]) < 0.2
    best, best_a = None, alphas[0]
    for a in alphas:
        m = Ridge(alpha=a, solver="sparse_cg", max_iter=3000, tol=1e-5).fit(X[~test], y[~test], sample_weight=w[~test])
        err = np.average((m.predict(X[test]) - y[test]) ** 2, weights=w[test])
        if best is None or err < best:
            best, best_a = err, a
    m = Ridge(alpha=best_a, solver="sparse_cg", max_iter=3000, tol=1e-5).fit(X, y, sample_weight=w)
    return m.coef_, best_a


def _situation(d: pd.DataFrame) -> pd.DataFrame:
    s = pd.DataFrame(index=d.index)
    s["dd"] = np.select([d.down == 1, d.ydstogo <= 3, d.ydstogo <= 7], ["1", "s", "m"], "l") + d.down.fillna(1).astype(int).astype(str)
    s["zone"] = pd.cut(d.yardline_100, [0, 10, 20, 50, 80, 100], labels=False).fillna(2)
    s["rushers"] = d.number_of_pass_rushers.fillna(4).clip(3, 6)
    s["box"] = d.defenders_in_box.fillna(7).clip(5, 9)
    s["season"] = d.season
    return s


def fit_all(d: pd.DataFrame, of: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """선수별 계수 긴 표 (gsis_id, metric, coef)와 선택된 벌점."""
    out, info = [], {}
    sit = _situation(d)

    def run_model(name, mask, y, controls, split=None, metrics=None):
        sub = d[mask]
        keys = sub.key.values
        X, cols = _design(of, keys, split)
        C = _controls(sit.loc[sub.index], controls)
        coef, a = _fit(sparse.hstack([X, C]).tocsr(), y[mask].values.astype(float), sub.w.values)
        info[name] = {"alpha": a, "plays": int(mask.sum()), "players": int(len(cols))}
        c = pd.Series(coef[: len(cols)], index=cols)
        parts = c.index.str.split(":")
        df = pd.DataFrame({"side": parts.str[0], "gsis_id": parts.str[1],
                           "tag": parts.str[2] if split is not None else "", "coef": c.values})
        for (side, tag), metric in metrics.items():
            s = df[(df.side == side) & (df.tag == tag)]
            out.append(pd.DataFrame({"gsis_id": s.gsis_id, "metric": metric, "coef": s.coef}))

    has_part = d.offense_players.notna()
    press = d.is_db & has_part & d.was_pressure.notna()
    run_model("pressure", press, d.was_pressure.astype(float), ["dd", "rushers", "season"],
              metrics={("off", ""): "rapm_pressure_off", ("def", ""): "rapm_pressure_def"})
    run = d.is_run & has_part
    run_model("run", run, d.epa_c, ["dd", "zone", "box", "season"],
              metrics={("off", ""): "rapm_run_off", ("def", ""): "rapm_run_def"})
    cov = d.is_db & has_part & (d["cov"] != "")
    run_model("coverage", cov, d.epa_c, ["dd", "zone", "rushers", "season"], split=d.set_index("key")["cov"],
              metrics={("def", "man"): "rapm_cov_man", ("def", "zone"): "rapm_cov_zone"})
    run_model("coverage_all", d.is_db & has_part, d.epa_c, ["dd", "zone", "season"],
              metrics={("def", ""): "rapm_cov_all", ("off", ""): "rapm_pass_off"})
    return pd.concat(out, ignore_index=True), info
