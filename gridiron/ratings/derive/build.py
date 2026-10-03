"""능력치 산출 본체: 지표 → 수축 → 백분위 → 1–20 → 조합 → F2-5d 보정 → CSV.

수축(경험적 베이즈): 선수 i의 지표 평균 x̄ᵢ(표본 nᵢ)를
    θᵢ = (nᵢ·x̄ᵢ + k·priorᵢ) / (nᵢ + k),   k = 잡음 분산 / 선수 간 실제 분산
으로 당긴다. priorᵢ는 같은 포지션에서 드래프트 순위·출전량·뎁스 순번·경력으로 회귀한 예측값이다.
"팀이 잘 안 쓰는 선수는 대체로 덜 좋다"는 정보가 여기서 들어가, 기록이 적은 백업이 평균 주전 값으로 뜨지 않는다.

백분위: 같은 포지션 선수들의 **스냅 가중** 분포에서의 위치. 스냅 가중이므로 중앙값이 "필드에 서는 평균 선수"다.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ...domain.attributes import ATTR_KEYS, clamp
from ...domain.positions import Position
from ..position_rating import weights as pr_weights
from ..provisional import generate_attributes, seeded_rng
from . import health, metrics, physical, rapm
from .plays import load_plays, on_field, window
from .recipes import OFFSET, PHYS_BLEND, RECIPE_GROUP, RECIPES, RUSH_TILT

# 백분위 → 1–20 (F2-5a: 상위 0.5% ≈ 20, 3% ≈ 18, 10% ≈ 16, 25% ≈ 14, 45% ≈ 12.5, 하위 10% ≈ 7)
P2R = [(0.0, 4.0), (0.05, 6.0), (0.10, 7.0), (0.30, 9.0), (0.50, 11.8), (0.55, 12.5), (0.75, 14.3),
       (0.90, 16.2), (0.97, 18.0), (0.995, 19.5), (1.0, 20.0)]
P2R_MED = [(0.0, 4.0), (0.10, 7.0), (0.30, 9.5), (0.50, 11.5), (0.70, 13.0), (0.90, 15.5), (0.98, 18.0), (1.0, 19.0)]
K_RAPM = 250.0           # RAPM 계수는 릿지가 이미 수축했으므로 사전값과의 혼합만 약하게
STARTER_PR_TARGET = 13.0  # F2-5d: 주전 PR 평균 12.5–13.5
MAX_ELITE = 3             # F2-5d: PR 17.0 이상은 포지션당 1–3명
DEF_POS = {"EDGE", "DT", "LB", "CB", "S"}
OFF_POS = {"QB", "RB", "FB", "WR", "TE", "OT", "OG", "C"}


def p2r(p: np.ndarray, table=P2R) -> np.ndarray:
    xs, ys = zip(*table)
    return np.interp(p, xs, ys)


def wpct(values: np.ndarray, ref: np.ndarray, ref_w: np.ndarray) -> np.ndarray:
    """values 각각의 ref(가중치 ref_w) 분포 내 백분위 (동점은 절반)."""
    order = np.argsort(ref)
    rs, rw = ref[order], ref_w[order]
    cum = np.concatenate([[0.0], np.cumsum(rw)])
    lo = np.searchsorted(rs, values, side="left")
    hi = np.searchsorted(rs, values, side="right")
    return (cum[lo] + 0.5 * (cum[hi] - cum[lo])) / cum[-1]


def wmean_sd(x: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    m = float(np.average(x, weights=w))
    sd = float(math.sqrt(np.average((x - m) ** 2, weights=w)))
    return m, max(sd, 1e-9)


# ── 수축 ────────────────────────────────────────────────────────────
def prior_features(ros: pd.DataFrame, target: int) -> np.ndarray:
    pick = pd.to_numeric(ros.draft_pick, errors="coerce")
    dc = np.where(pick.notna(), np.log(300 / pick.clip(1, 299)), 0.0)
    exp = pd.to_numeric(ros.years_exp, errors="coerce").fillna(0)
    rookie = (exp == 0) | (pd.to_numeric(ros.draft_year, errors="coerce") == target)
    ls = np.log1p(ros.snaps.values)
    vet = ~rookie.values
    if vet.any():
        ls = np.where(rookie.values, np.median(ls[vet]), ls)  # 신인은 출전량 정보가 없으므로 중립값
    dr = pd.to_numeric(ros.depth_rank, errors="coerce")
    return np.column_stack([np.ones(len(ros)), dc, ls, (dr == 1).astype(float), (dr == 2).astype(float),
                            np.minimum(exp, 10) / 10])


def shrink(mean: np.ndarray, n: np.ndarray, var: np.ndarray | None, X: np.ndarray) -> tuple[np.ndarray, float]:
    have = n > 0
    if have.sum() < 5:
        return np.zeros(len(n)), float("nan")
    m, nn = mean[have], n[have]
    if var is None:
        k = K_RAPM
    else:
        mu = np.average(m, weights=nn)
        sigma2 = np.average(var[have], weights=nn)
        between = np.average((m - mu) ** 2, weights=nn)
        noise = sigma2 * have.sum() / nn.sum()
        tau2 = max(between - noise, 0.1 * between, 1e-12)
        k = sigma2 / tau2
    # 사전값 회귀 (신뢰도 가중 + 작은 릿지)
    rel = nn / (nn + k)
    Xh = X[have]
    A = Xh.T @ (Xh * rel[:, None]) + 0.5 * np.eye(X.shape[1]) * rel.sum() / len(rel)
    beta = np.linalg.solve(A, Xh.T @ (rel * m))
    prior = X @ beta
    x = np.where(have, mean, 0.0)
    return (n * x + k * prior) / (n + k), float(k)


# ── 본체 ────────────────────────────────────────────────────────────
def build(target: int, cache: Path, data_dir: Path) -> tuple[pd.DataFrame, dict]:
    seasons = window(target)
    base = data_dir / "real" / str(target)
    ros = pd.read_csv(base / "players.csv", dtype={"gsis_id": str})
    meta = json.loads((base / "meta.json").read_text())
    season_start = date.fromisoformat(meta["first_game_day"])

    d = load_plays(cache, seasons)
    of = on_field(d)
    long = metrics.all_metrics(d, of, cache, seasons)
    coefs, rapm_info = rapm.fit_all(d, of)
    snaps = metrics.snaps(of)
    hm = health.health_metrics(cache, seasons)

    # 선수별 출전량 (자기 쪽 스냅, K/P는 시도 수)
    off_snaps = (snaps.get("db_off", 0) + snaps.get("run_off", 0)).rename("off")
    def_snaps = (snaps.get("db_def", 0) + snaps.get("run_def", 0)).rename("def")
    ros = ros.join(off_snaps, on="gsis_id").join(def_snaps, on="gsis_id")
    kp = long[long.metric.isin(["fg_oe", "punt_gross"])].groupby("gsis_id").n.sum()
    ros["snaps"] = np.where(ros.position.isin(DEF_POS), ros["def"], np.where(ros.position.isin(["K", "P"]),
                            ros.gsis_id.map(kp), ros["off"]))
    ros["snaps"] = pd.to_numeric(ros.snaps, errors="coerce").fillna(0.0)
    snap_n = {"rapm_pressure_off": snaps.get("db_off"), "rapm_run_off": snaps.get("run_off"),
              "rapm_pressure_def": snaps.get("db_def"), "rapm_run_def": snaps.get("run_def"),
              "rapm_cov_man": snaps.get("man_def"), "rapm_cov_zone": snaps.get("zone_def"),
              "rapm_cov_all": snaps.get("db_def"), "rapm_pass_off": snaps.get("db_off")}

    wide_mean = long.pivot_table(index="gsis_id", columns="metric", values="mean")
    wide_n = long.pivot_table(index="gsis_id", columns="metric", values="n")
    wide_var = long.pivot_table(index="gsis_id", columns="metric", values="var")
    coef_wide = coefs.pivot_table(index="gsis_id", columns="metric", values="coef")

    meas = physical.combine_measures(cache, ros)
    phys, phys_report = physical.physical_ratings(meas, ros, season_start)

    attrs: dict[str, dict[str, float]] = {}
    shrink_k: dict[str, dict[str, float]] = {}
    for pos, grp in ros.groupby("position"):
        ids = grp.gsis_id.values
        X = prior_features(grp, target)
        ref_w = grp.snaps.values + 5.0
        recipe = RECIPES.get(RECIPE_GROUP.get(pos, pos), {})
        needed = sorted({m for parts in recipe.values() for m, _ in parts})
        z: dict[str, np.ndarray] = {}
        for metric in needed:
            if metric.startswith("rapm_"):
                mean = coef_wide.get(metric, pd.Series(dtype=float)).reindex(ids).values
                n = snap_n[metric].reindex(ids).fillna(0).values if snap_n.get(metric) is not None else np.zeros(len(ids))
                n = np.where(np.isnan(mean), 0, n)
                var = None
            else:
                mean = wide_mean.get(metric, pd.Series(dtype=float)).reindex(ids).values
                n = wide_n.get(metric, pd.Series(dtype=float)).reindex(ids).fillna(0).values
                var = wide_var.get(metric, pd.Series(dtype=float)).reindex(ids).values
                var = np.where(np.isnan(var), np.nanmedian(var) if np.isfinite(var).any() else 1.0, var)
            mean = np.where(np.isnan(mean), 0.0, mean)
            th, k = shrink(mean, n, var, X)
            shrink_k.setdefault(pos, {})[metric] = round(k, 2) if np.isfinite(k) else None
            mu, sd = wmean_sd(th, ref_w)
            z[metric] = (th - mu) / sd
        for i, pid in enumerate(ids):
            attrs[pid] = {}
        for attr, parts in recipe.items():
            comp = sum(w * z[m] for m, w in parts) / sum(abs(w) for _, w in parts)
            r = p2r(wpct(comp, comp, ref_w)) + OFFSET.get(pos, {}).get(attr, 0.0)
            for pid, v in zip(ids, r):
                attrs[pid][attr] = v
        # 신체
        for pid in ids:
            for k in ("speed", "strength", "jumping", "agility", "acceleration"):
                attrs[pid][k] = float(phys.at[pid, k])
        # 신체 혼합·패스 러시 스타일
        for attr, phys_key, w in PHYS_BLEND.get(pos, []):
            for pid in ids:
                if attr in attrs[pid]:
                    attrs[pid][attr] = (1 - w) * attrs[pid][attr] + w * attrs[pid][phys_key]
        if pos in ("EDGE", "DT", "LB"):
            sp = np.array([attrs[p]["speed"] for p in ids])
            st = np.array([attrs[p]["strength"] for p in ids])
            tilt = (sp - sp.mean()) - (st - st.mean())
            for pid, t in zip(ids, tilt):
                attrs[pid]["finesse_rush"] += RUSH_TILT * t / 2
                attrs[pid]["power_rush"] -= RUSH_TILT * t / 2
        # 지구력
        if pos not in ("K", "P", "LS"):
            mean = wide_mean.get("stamina_pct", pd.Series(dtype=float)).reindex(ids).values
            n = wide_n.get("stamina_pct", pd.Series(dtype=float)).reindex(ids).fillna(0).values
            var = wide_var.get("stamina_pct", pd.Series(dtype=float)).reindex(ids).fillna(0.05).values
            th, _ = shrink(np.nan_to_num(mean), n, var, X)
            r = p2r(wpct(th, th, np.ones(len(th))))
            for pid, v in zip(ids, r):
                attrs[pid]["stamina"] = v

    # 의료 (숨김): 전 포지션 한 집단
    all_ids = ros.gsis_id.values
    Xc = np.ones((len(all_ids), 1))
    med = {}
    for metric, attr, sign in (("missed_rate", "durability", -1), ("q_played", "pain_tolerance", 1),
                               ("out_streak", "recovery", -1)):
        sub = hm[hm.metric == metric].set_index("gsis_id")
        mean = sub["mean"].reindex(all_ids).values
        n = sub["n"].reindex(all_ids).fillna(0).values
        var = sub["var"].reindex(all_ids).fillna(sub["var"].median()).values
        th, k = shrink(np.nan_to_num(mean), n, var, Xc)
        med[attr] = p2r(wpct(sign * th, sign * th, np.ones(len(th))), P2R_MED)
        shrink_k.setdefault("ALL", {})[metric] = round(k, 2)

    # ── 조합: 임시 생성기 바탕 위에 실측값을 덮는다 ──
    out_rows = []
    dr_all = pd.to_numeric(ros.depth_rank, errors="coerce")
    for idx, r in ros.iterrows():
        pid, pos = r.gsis_id, Position(r.position)
        m = attrs[pid]
        w = dict(pr_weights(pos))
        have = {k: v for k, v in w.items() if k in m}
        q = sum(m[k] * v for k, v in have.items()) / sum(have.values()) if have else 10.0
        exp = int(pd.to_numeric(r.years_exp, errors="coerce") if pd.notna(r.years_exp) else 0)
        a = generate_attributes(pid, pos, q, years_exp=exp,
                                height_in=int(r.height_in) if pd.notna(r.height_in) else None,
                                weight_lb=int(r.weight_lb) if pd.notna(r.weight_lb) else None)
        a.update(m)
        rng = seeded_rng(pid, "mental")
        starter = dr_all[idx] == 1
        exp_term = 8 + 0.75 * min(exp, 10)
        if pos == Position.QB:
            a["football_iq"] = 0.5 * a["decision"] + 0.25 * q + 0.25 * exp_term + rng.gauss(0, 0.8)
            a["composure"] = 0.5 * a["composure"] + 0.5 * q
        else:
            a["football_iq"] = 0.5 * q + 0.5 * exp_term + rng.gauss(0, 1.0)
        a["leadership"] = 6 + 0.55 * min(exp, 12) + 1.5 * starter + (1.5 if pos == Position.QB else 0) + rng.gauss(0, 1.2)
        for k in ("durability", "pain_tolerance", "recovery"):
            a[k] = float(med[k][idx])
        out_rows.append({"gsis_id": pid, **{k: clamp(float(a[k])) for k in ATTR_KEYS}})

    rat = pd.DataFrame(out_rows).set_index("gsis_id")
    info = ros.set_index("gsis_id")[["name", "team", "position", "roster_status", "depth_rank", "snaps"]]
    calib = calibrate(rat, info)
    rat = rat.round(2)
    rat.insert(0, "pr", [round(pr_of(rat.loc[p], Position(info.at[p, "position"])), 1) for p in rat.index])
    basis = np.where(info.snaps.values >= np.where(info.position.isin(["K", "P"]), 10, 100), "measured", "prior")
    rat.insert(0, "basis", basis)
    rat.insert(0, "snaps", info.snaps.round(0).astype(int).values)
    for c in ("depth_rank", "position", "team", "name"):
        rat.insert(0, c, info[c].values)
    report = {"target_season": target, "history_seasons": seasons, "rapm": rapm_info, "shrink_k": shrink_k,
              "physical": phys_report, "calibration": calib, "validation": validate(rat)}
    return rat.reset_index(), report


def pr_of(row, pos: Position) -> float:
    return sum(row[k] * w for k, w in pr_weights(pos))


def calibrate(rat: pd.DataFrame, info: pd.DataFrame) -> dict:
    """F2-5d: 포지션별 주전 PR 평균을 13.0으로, PR 17 이상을 3명 이하로 (실측 기술 능력치의 이동·압축)."""
    out = {}
    active = info.roster_status == "active"
    for pos_s, ids in info[active].groupby("position").groups.items():
        pos = Position(pos_s)
        recipe = RECIPES.get(RECIPE_GROUP.get(pos_s, pos_s), {})
        tech = [k for k in recipe if k in dict(pr_weights(pos))]
        share = sum(w for k, w in pr_weights(pos) if k in tech)
        if not tech or share < 0.2:
            continue
        all_pos = info.index[info.position == pos_s]
        starters = [p for p in ids if pd.to_numeric(info.at[p, "depth_rank"], errors="coerce") == 1]
        if not starters:
            continue
        shift = 0.0
        for _ in range(3):
            prs = np.array([pr_of(rat.loc[p], pos) for p in starters])
            delta = float(np.clip((STARTER_PR_TARGET - prs.mean()) / share, -3, 3))
            rat.loc[all_pos, tech] = (rat.loc[all_pos, tech] + delta).clip(1, 20)
            shift += delta
        factor = 1.0
        for _ in range(60):
            prs_all = np.array([pr_of(rat.loc[p], pos) for p in ids])
            if (prs_all >= 16.95).sum() <= MAX_ELITE:  # 소수 1자리 반올림 후 17.0이 되는 값까지
                break
            factor *= 0.97
            sub = rat.loc[all_pos, tech]
            rat.loc[all_pos, tech] = sub.where(sub <= 12, 12 + (sub - 12) * 0.97)
        out[pos_s] = {"tech_shift": round(shift, 2), "top_compression": round(factor, 3)}
    # 리그 전체 능력치별 상단: 19.5 이상은 3명까지 (포지션마다 따로 백분위를 매기면 리그 전체로는 상단이 겹친다)
    act_ids = info.index[info.team.notna() & (info.team != "")]  # 검증과 같은 집단 (연습 스쿼드 포함)
    league = {}
    for k in ATTR_KEYS:
        v = rat.loc[act_ids, k].to_numpy()
        third = np.sort(v)[-3]
        if (v >= 19.5).sum() > 3 and third > 16:
            f = (19.4 - 16) / (third - 16)
            col = rat[k]
            rat[k] = col.where(col <= 16, 16 + (col - 16) * f)
            league[k] = round(f, 3)
    out["league_top_compression"] = league
    return out


def validate(rat: pd.DataFrame) -> dict:
    act = rat[rat.team.notna() & (rat.team != "")]
    res = {"starter_pr_mean": {}, "elite_pr17": {}, "twenty_counts": {}, "pass": True}
    dr = pd.to_numeric(act.depth_rank, errors="coerce")
    for pos, g in act.groupby("position"):
        s = g[dr[g.index] == 1]
        if len(s):
            m = round(float(s.pr.mean()), 2)
            res["starter_pr_mean"][pos] = m
            if pos not in ("LS",) and not (12.5 <= m <= 13.5):
                res["pass"] = False
        res["elite_pr17"][pos] = int((g.pr >= 17.0).sum())
        if res["elite_pr17"][pos] > MAX_ELITE:
            res["pass"] = False
    from ...domain.attributes import VISIBLE_KEYS
    for k in VISIBLE_KEYS:
        c = int((act[k] >= 19.5).sum())
        if c:
            res["twenty_counts"][k] = c
        if c > 3:
            res["pass"] = False
    return res


def write(rat: pd.DataFrame, report: dict, out_dir: Path) -> None:
    rat.to_csv(out_dir / "ratings.csv", index=False)
    (out_dir / "ratings_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                                                 encoding="utf-8")
    ov = out_dir / "ratings_overrides.csv"
    if not ov.exists():
        ov.write_text("gsis_id,attribute,value,note\n", encoding="utf-8")
