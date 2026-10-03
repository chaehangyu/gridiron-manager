"""선수별 실측 지표 (PRD §7.2 표).

모든 지표는 긴 표 `gsis_id, metric, mean, n, var`로 낸다.
- mean: 시즌 가중 평균 (플레이·시도·스냅 단위)
- n: 가중 표본 수 (수축 강도 계산용)
- var: 표본 1개당 분산 (경험적 베이즈의 잡음 분산)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ...baseline.tables import tables


def acc(ids: pd.Series, vals: pd.Series, w: pd.Series, metric: str) -> pd.DataFrame:
    m = ids.notna() & vals.notna()
    df = pd.DataFrame({"gsis_id": ids[m].values, "v": vals[m].astype(float).values, "w": w[m].astype(float).values})
    df["wv"] = df.w * df.v
    df["wvv"] = df.w * df.v ** 2
    g = df.groupby("gsis_id")[["w", "wv", "wvv"]].sum()
    out = pd.DataFrame({"gsis_id": g.index, "n": g.w.values, "mean": (g.wv / g.w).values})
    out["var"] = np.maximum((g.wvv / g.w).values - out["mean"].values ** 2, 1e-6)
    out["metric"] = metric
    return out


# ── 플레이 이벤트 → 선수 크레딧 ─────────────────────────────────────
CREDITS = {
    "sack": [("sack_player_id", 1.0), ("half_sack_1_player_id", 0.5), ("half_sack_2_player_id", 0.5)],
    "hit": [("qb_hit_1_player_id", 1.0), ("qb_hit_2_player_id", 1.0)],
    "tfl": [("tackle_for_loss_1_player_id", 1.0), ("tackle_for_loss_2_player_id", 1.0)],
    "tkl": [("solo_tackle_1_player_id", 1.0), ("solo_tackle_2_player_id", 1.0), ("tackle_with_assist_1_player_id", 1.0),
            ("tackle_with_assist_2_player_id", 1.0), ("assist_tackle_1_player_id", 0.5),
            ("assist_tackle_2_player_id", 0.5)],
    "pd": [("pass_defense_1_player_id", 1.0), ("pass_defense_2_player_id", 1.0)],
    "int": [("interception_player_id", 1.0)],
    "ff": [("forced_fumble_player_1_player_id", 1.0)],
}


def credits(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ev, cols in CREDITS.items():
        for col, amt in cols:
            s = d.loc[d[col].notna(), ["key", col]].rename(columns={col: "gsis_id"})
            s["ev"] = ev
            s["amt"] = amt
            rows.append(s)
    c = pd.concat(rows, ignore_index=True)
    return c.pivot_table(index=["key", "gsis_id"], columns="ev", values="amt", aggfunc="sum", fill_value=0).reset_index()


def defense_box(d: pd.DataFrame, of: pd.DataFrame) -> list[pd.DataFrame]:
    """수비수: 스냅당 생산성 (필드에 있던 스냅이 분모)."""
    dfn = of[of.side == "def"].merge(credits(d), on=["key", "gsis_id"], how="left").fillna(
        {k: 0.0 for k in CREDITS})
    plays = d.set_index("key")[["yards_gained"]]
    dfn = dfn.join(plays, on="key")
    db, run = dfn[dfn.is_db], dfn[dfn.is_run]
    out = [
        acc(db.gsis_id, db["sack"] + 0.5 * db["hit"], db.w, "rush_prod"),
        acc(run.gsis_id, run["tfl"], run.w, "tfl_rate"),
        acc(run.gsis_id, run["tkl"] * (run.yards_gained <= 3), run.w, "run_stop_tkl"),
        acc(dfn.gsis_id, dfn["tkl"], dfn.w, "tackle_rate"),
        acc(dfn.gsis_id, dfn["tkl"] * (dfn.yards_gained >= 8), dfn.w, "pursuit_tkl"),
        acc(db.gsis_id, db["pd"] + db["int"], db.w, "ball_prod"),
        acc(db.gsis_id, db["int"], db.w, "int_rate"),
        acc(dfn.gsis_id, dfn["ff"], dfn.w, "ff_rate"),
    ]
    return out


def snaps(of: pd.DataFrame) -> pd.DataFrame:
    """필드 스냅 수 (시즌 가중): db_off, run_off, db_def, run_def, man_def, zone_def."""
    of = of.copy()
    of["db"] = of.w * of.is_db
    of["run"] = of.w * of.is_run
    of["man"] = of.w * (of.cov == "man")
    of["zone"] = of.w * (of.cov == "zone")
    g = of.groupby(["gsis_id", "side"])[["db", "run", "man", "zone"]].sum().unstack("side", fill_value=0)
    g.columns = [f"{a}_{b}" for a, b in g.columns]
    return g


def offense_box(d: pd.DataFrame, of: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    att = d[d.is_att]
    db = d[d.is_db]
    # ── QB ──
    for name, lo, hi in (("cpoe_short", -99, 10), ("cpoe_med", 10, 20), ("cpoe_deep", 20, 99)):
        s = att[(att.air_yards >= lo) & (att.air_yards < hi) & att.cpoe.notna()]
        out.append(acc(s.passer_player_id, s.cpoe / 100, s.w, name))
    s = att[att.is_interception_worthy.notna()]
    out.append(acc(s.passer_player_id, s.is_interception_worthy.astype(float), s.w, "itw_rate"))
    out.append(acc(db.db_qb, db.qb_epa.clip(-4, 4), db.w, "qb_epa"))
    out.append(acc(db.db_qb, (db.fumbled_1_player_id == db.db_qb).astype(float), db.w, "qb_fumble"))
    # 승부처(4쿼터·연장, 승률 20–80%) 성적 — 침착성
    clutch = db[(db.qtr >= 4) & db.wp.between(0.2, 0.8)]
    out.append(acc(clutch.db_qb, clutch.qb_epa.clip(-4, 4), clutch.w, "qb_epa_clutch"))
    s = db[db.was_pressure.notna() & (db.was_pressure == True)]  # noqa: E712
    out.append(acc(s.db_qb, s.sack.astype(float), s.w, "sack_when_pressured"))
    s = db[db.is_qb_fault_sack.notna()]
    out.append(acc(s.db_qb, s.is_qb_fault_sack.astype(float), s.w, "qb_fault_sack"))
    s = att[(att.is_qb_out_of_pocket == True) & att.cpoe.notna()]  # noqa: E712
    out.append(acc(s.passer_player_id, s.cpoe / 100, s.w, "cpoe_on_run"))
    out.append(acc(att.passer_player_id, (att.air_yards >= 20).astype(float), att.w, "deep_share"))
    s = d[(d.qb_scramble == 1)]
    out.append(acc(s.rusher_player_id, s.yards_gained.clip(-5, 40), s.w, "scramble_yds"))

    # ── 볼 캐리어 ──
    run = d[d.is_run]
    out.append(acc(run.rusher_player_id, (run.yards_gained >= 10).astype(float), run.w, "explosive_run"))
    out.append(acc(run.rusher_player_id, (run.yards_gained > 0).astype(float), run.w, "no_stuff"))
    out.append(acc(run.rusher_player_id, run.success.astype(float), run.w, "run_success"))
    s = run[run.ydstogo <= 2]
    out.append(acc(s.rusher_player_id, s.first_down.fillna(0).astype(float) + s.touchdown.fillna(0), s.w, "short_conv"))
    rec = att[(att.complete_pass == 1) & att.xyac_mean_yardage.notna()]
    out.append(acc(rec.receiver_player_id, (rec.yards_after_catch - rec.xyac_mean_yardage).clip(-10, 40), rec.w,
                   "yac_oe"))
    touches = pd.concat([run[["rusher_player_id", "w", "fumbled_1_player_id"]].rename(columns={"rusher_player_id": "id"}),
                         rec[["receiver_player_id", "w", "fumbled_1_player_id"]].rename(
                             columns={"receiver_player_id": "id"})])
    out.append(acc(touches.id, (touches.fumbled_1_player_id == touches.id).astype(float), touches.w, "fumble_rate"))

    # ── 리시버 ──
    tgt = att[att.receiver_player_id.notna()]
    s = tgt[tgt.is_catchable_ball == True]  # noqa: E712
    out.append(acc(s.receiver_player_id, s.is_drop.astype(float), s.w, "drop_rate"))
    s = tgt[tgt.cp.notna()]
    out.append(acc(s.receiver_player_id, s.complete_pass - s.cp, s.w, "catch_oe"))
    s = tgt[tgt.is_contested_ball == True]  # noqa: E712
    out.append(acc(s.receiver_player_id, s.complete_pass.astype(float), s.w, "contested_rate"))
    # 루트당 타깃·야드: 필드에 있던 드롭백 스냅이 분모
    offdb = of[(of.side == "off") & of.is_db][["key", "gsis_id", "w", "cov"]]
    t = tgt[["key", "receiver_player_id", "yards_gained", "complete_pass"]].rename(columns={"receiver_player_id": "gsis_id"})
    m = offdb.merge(t, on=["key", "gsis_id"], how="left")
    m["tg"] = m.yards_gained.notna().astype(float)
    m["yd"] = np.where(m.complete_pass == 1, m.yards_gained, 0.0)
    out.append(acc(m.gsis_id, m.tg, m.w, "tprr"))
    out.append(acc(m.gsis_id, m.yd.clip(-5, 60), m.w, "yprr"))
    mm = m[m["cov"] == "man"]
    out.append(acc(mm.gsis_id, mm.tg, mm.w, "tprr_man"))
    return out


def ngs(cache: Path, seasons: dict[int, float]) -> list[pd.DataFrame]:
    out = []
    rec = pd.read_parquet(cache / "ngs_receiving.parquet")
    rec = rec[rec.season.isin(seasons) & (rec.week > 0)]
    w = rec.season.map(seasons) * rec.targets
    out.append(acc(rec.player_gsis_id, rec.avg_separation, w, "separation"))
    rush = pd.read_parquet(cache / "ngs_rushing.parquet")
    rush = rush[rush.season.isin(seasons) & (rush.week > 0)]
    w = rush.season.map(seasons) * rush.rush_attempts
    out.append(acc(rush.player_gsis_id, rush.rush_yards_over_expected_per_att.clip(-4, 6), w, "ryoe"))
    p = pd.read_parquet(cache / "ngs_passing.parquet")
    p = p[p.season.isin(seasons) & (p.week == 0)]
    w = p.season.map(seasons) * p.attempts
    out.append(acc(p.player_gsis_id, p.max_air_distance, w, "max_air"))
    return out


def special(d: pd.DataFrame) -> list[pd.DataFrame]:
    out = []
    fg_tab = tables()["special"]["fg_make_by_yard"]
    fg = d[(d.play_type == "field_goal") & d.kick_distance.notna()]
    exp = fg.kick_distance.clip(18, 70).round().astype(int).astype(str).map(fg_tab).astype(float)
    made = (fg.field_goal_result == "made").astype(float)
    out.append(acc(fg.kicker_player_id, made - exp, fg.w, "fg_oe"))
    lg = fg[fg.kick_distance >= 50]
    out.append(acc(lg.kicker_player_id, made[lg.index] - exp[lg.index], lg.w, "fg_long_oe"))
    out.append(acc(fg.kicker_player_id, (fg.kick_distance >= 50).astype(float), fg.w, "fg_long_share"))
    xp = d[d.play_type == "extra_point"]
    out.append(acc(xp.kicker_player_id, (xp.extra_point_result == "good").astype(float), xp.w, "xp_rate"))
    pu = d[(d.play_type == "punt") & d.kick_distance.notna() & (d.punt_blocked != 1)]
    deep = pu[pu.yardline_100 >= 60]
    out.append(acc(deep.punter_player_id, deep.kick_distance.clip(20, 75), deep.w, "punt_gross"))
    short = pu[(pu.yardline_100 >= 35) & (pu.yardline_100 < 60)]
    out.append(acc(short.punter_player_id, short.punt_inside_twenty.fillna(0) - short.touchback.fillna(0), short.w,
                   "punt_pin"))
    for typ, col in (("kick_return", "kickoff_returner_player_id"), ("punt_return", "punt_returner_player_id")):
        r = d[d[col].notna() & d.return_yards.notna()]
        base = r.groupby("season").return_yards.transform("mean")
        out.append(acc(r[col], (r.return_yards - base).clip(-20, 60), r.w, typ))
    return out


def all_metrics(d: pd.DataFrame, of: pd.DataFrame, cache: Path, seasons: dict[int, float]) -> pd.DataFrame:
    parts = offense_box(d, of) + defense_box(d, of) + ngs(cache, seasons) + special(d)
    return pd.concat(parts, ignore_index=True)
