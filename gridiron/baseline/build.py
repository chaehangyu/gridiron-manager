"""실측 기준 분포 테이블 생성 (ENGINE_DESIGN §5, PRD M2).

nflverse 2022–2025 pbp + 2023–2025 참여 데이터 + 2022–2025 FTN 차팅으로 만든다.
결과는 `data/baseline/tables.json` (게임 실행 시에는 pandas 없이 읽는다).

    python -m gridiron.baseline.build --cache data/raw

필요 패키지: pandas, pyarrow
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DATA_DIR

BASE_URL = "https://github.com/nflverse/nflverse-data/releases/download"
PBP_SEASONS = (2022, 2023, 2024, 2025)
PART_SEASONS = (2023, 2024, 2025)
KICKOFF_SEASONS = (2025,)  # 2025년 킥오프 규칙 기준

# 분위수 격자: 0–100 1% 간격 + 꼬리 보강
PCTS = sorted(set(list(range(0, 101)) + [0.5, 99.5, 99.8]))
MIN_N_QUANT = 250
MIN_N_RATE = 150

COV_MAP = {"COVER_0": "C0", "COVER_1": "C1", "2_MAN": "2M", "COVER_2": "C2", "COVER_3": "C3",
           "COVER_4": "QTR", "COVER_6": "QTR", "COVER_9": "QTR"}
COVERS = ["C0", "C1", "2M", "C2", "C3", "QTR"]
DEPTHS = ["screen", "quick", "inter", "deep"]
BOXES = ["light", "normal", "heavy"]
PERSONNEL = ["11", "12", "21", "13", "22", "10"]


def fetch(cache: Path, rel: str) -> Path:
    dst = cache / Path(rel).name
    if not dst.exists():
        cache.mkdir(parents=True, exist_ok=True)
        print(f"download {rel}")
        urllib.request.urlretrieve(f"{BASE_URL}/{rel}", dst)
    return dst


def dd_class(down, togo) -> str:
    if down == 1:
        return "1st"
    if down == 2:
        return "2s" if togo <= 3 else ("2m" if togo <= 7 else "2l")
    return f"{int(min(down, 4))}" + ("s" if togo <= 2 else ("m" if togo <= 6 else "l"))


def zone(yardline_100) -> str:
    if yardline_100 >= 90:
        return "backed"
    if yardline_100 > 20:
        return "open"
    if yardline_100 > 5:
        return "red"
    return "goal"


def personnel(s) -> str | None:
    if not isinstance(s, str):
        return None
    rb = re.search(r"(\d) RB", s)
    fb = re.search(r"(\d) FB", s)
    te = re.search(r"(\d) TE", s)
    n_rb = (int(rb.group(1)) if rb else 0) + (int(fb.group(1)) if fb else 0)
    n_te = int(te.group(1)) if te else 0
    key = f"{n_rb}{n_te}"
    return key if key in PERSONNEL else "other"


def def_personnel(s) -> str | None:
    if not isinstance(s, str):
        return None
    dbs = sum(int(n) for n, pos in re.findall(r"(\d) (CB|FS|SS|S|DB)\b", s))
    return "base" if dbs <= 4 else ("nickel" if dbs == 5 else "dime")


def load(cache: Path) -> pd.DataFrame:
    cols = ["game_id", "play_id", "season", "season_type", "play_type", "posteam", "defteam", "down", "ydstogo",
            "yardline_100", "epa", "success", "xpass", "air_yards", "yards_after_catch", "yards_gained",
            "complete_pass", "incomplete_pass", "interception", "sack", "qb_scramble", "qb_dropback", "run_gap",
            "run_location", "fumble", "fumble_lost", "touchdown", "first_down", "wp", "penalty",
            "two_point_attempt", "two_point_conv_result"]
    frames = []
    for y in PBP_SEASONS:
        pb = pd.read_parquet(fetch(cache, f"pbp/play_by_play_{y}.parquet"), columns=cols)
        ft = pd.read_parquet(fetch(cache, f"ftn_charting/ftn_charting_{y}.parquet"))[
            ["nflverse_game_id", "nflverse_play_id", "n_defense_box", "is_play_action", "is_screen_pass",
             "n_blitzers", "is_qb_sneak", "is_throw_away"]]
        d = pb.merge(ft, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "nflverse_play_id"], how="left")
        if y in PART_SEASONS:
            pa = pd.read_parquet(fetch(cache, f"pbp_participation/pbp_participation_{y}.parquet"))[
                ["nflverse_game_id", "play_id", "offense_personnel", "defense_personnel", "defenders_in_box",
                 "was_pressure", "defense_coverage_type"]]
            d = d.merge(pa, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="left",
                        suffixes=("", "_pa"))
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    d = d[d.play_type.isin(["pass", "run"]) & d.down.notna() & (d.two_point_attempt != 1)].copy()
    d["dd"] = [dd_class(a, b) for a, b in zip(d.down, d.ydstogo)]
    d["zone"] = d.yardline_100.map(zone)
    d["dropback"] = d.qb_dropback == 1
    d["kind"] = np.where(d.dropback, "pass", "run")
    d["box_n"] = d.n_defense_box.fillna(d.get("defenders_in_box"))
    d["box"] = pd.cut(d.box_n, [-1, 6, 7, 20], labels=BOXES).astype(object)
    d["blitz"] = (d.n_blitzers.fillna(0) >= 1).astype(int)
    d["covg"] = d.defense_coverage_type.map(COV_MAP)
    d["pers"] = d.offense_personnel.map(personnel)
    d["dpers"] = d.defense_personnel.map(def_personnel)
    d["pressure"] = d.was_pressure.map({True: 1, False: 0})
    d["pa"] = (d.is_play_action == True).astype(int)  # noqa: E712
    d["passing_down"] = d.dd.isin(["2l", "3m", "3l", "4m", "4l"]).astype(int)

    def depth(r):
        if r.is_screen_pass == True:  # noqa: E712
            return "screen"
        a = r.air_yards
        if pd.isna(a):
            return None
        return "quick" if a <= 5 else ("inter" if a <= 15 else "deep")

    d["depth"] = d.apply(depth, axis=1)

    def run_family(r):
        if r.is_qb_sneak == True:  # noqa: E712
            return "sneak"
        return "inside" if (r.run_gap == "guard" or r.run_location == "middle") else "outside"

    d["rfam"] = np.where(d.kind == "run", d.apply(run_family, axis=1), None)
    d.loc[d.qb_scramble == 1, "rfam"] = None
    return d


def quantiles(x: pd.Series) -> list[float]:
    q = [round(float(v), 2) for v in np.percentile(x.to_numpy(dtype=float), PCTS)]
    q[0] = q[1]  # 최솟값은 0.5 백분위수로 자른다 (스냅 실수 등 드문 예외 플레이 제거). 위쪽 꼬리(빅 플레이)는 유지
    return q


def levels(keys: list[str]) -> list[list[str]]:
    """세부 → 상위 순서의 집계 단계 (뒤에서부터 하나씩 '*'로)."""
    out = []
    for i in range(len(keys), -1, -1):
        out.append(keys[:i])
    return out


def grouped_table(df: pd.DataFrame, keys: list[str], fn, min_n: int) -> dict:
    """keys의 모든 부분 집계를 '|'로 이은 키로 저장. 표본 수 미달 칸은 저장하지 않는다."""
    table = {}
    for lv in levels(keys):
        if lv:
            groups = df.groupby(lv, observed=True)
        else:
            groups = [((), df)]
        for k, sub in groups:
            if len(sub) < min_n:
                continue
            k = k if isinstance(k, tuple) else (k,)
            full = list(map(str, k)) + ["*"] * (len(keys) - len(lv))
            table["|".join(full)] = fn(sub)
    return table


def distribution(series: pd.Series) -> dict[str, float]:
    vc = series.value_counts(normalize=True)
    return {str(k): round(float(v), 4) for k, v in vc.items()}


def build(cache: Path, out: Path) -> dict:
    d = load(cache)
    reg = d[d.season_type == "REG"]
    part = reg[reg.season.isin(PART_SEASONS)]
    T: dict = {"meta": {"pbp_seasons": PBP_SEASONS, "participation_seasons": PART_SEASONS, "pcts": PCTS,
                        "plays": int(len(reg))}}

    # ── 공격 콜 비율 ─────────────────────────────────────────
    runs = reg[(reg.kind == "run") & reg.rfam.notna()]
    T["run_family"] = grouped_table(runs, ["dd", "zone"], lambda s: distribution(s.rfam), MIN_N_RATE)
    passes = reg[reg.dropback & reg.depth.notna()]
    T["pass_depth"] = grouped_table(passes, ["dd", "zone"], lambda s: distribution(s.depth), MIN_N_RATE)
    T["pa_rate"] = grouped_table(passes[passes.depth != "screen"], ["dd", "zone"],
                                 lambda s: round(float(s.pa.mean()), 4), MIN_N_RATE)
    pers = part[part.pers.notna() & (part.pers != "other")]
    T["personnel"] = grouped_table(pers, ["kind", "dd"], lambda s: distribution(s.pers), MIN_N_RATE)

    # ── 수비 콜 비율 ─────────────────────────────────────────
    cov = part[part.dropback & part.covg.notna()]
    T["coverage"] = grouped_table(cov, ["dd", "pers"], lambda s: distribution(s.covg), MIN_N_RATE)
    T["blitz"] = grouped_table(cov, ["covg", "dd"], lambda s: round(float(s.blitz.mean()), 4), MIN_N_RATE)
    boxed = reg[reg.box.notna()]
    # 박스는 플레이 종류별로 저장한다: 실측에는 "평균적인 수비의 예상 적중"(런 예상 시 두꺼운 박스)이 들어 있다.
    # 경기 중 학습으로 이 적중률이 바뀌는 부분은 M4 코디네이터가 담당한다 (ENGINE_DESIGN §6).
    T["box"] = grouped_table(boxed, ["kind", "dd", "pers", "blitz"], lambda s: distribution(s.box), MIN_N_RATE)
    T["def_personnel"] = grouped_table(part[part.dpers.notna() & part.pers.notna()], ["pers"],
                                       lambda s: distribution(s.dpers), MIN_N_RATE)

    # ── 압박과 드롭백 분기 ──────────────────────────────────
    db = part[part.dropback & part.pressure.notna()].copy()
    db["pressure"] = db.pressure.astype(int)
    T["pressure"] = grouped_table(db[db.covg.notna()], ["covg", "blitz", "passing_down"],
                                  lambda s: round(float(s.pressure.mean()), 4), MIN_N_RATE)
    T["pressure_overall"] = round(float(db.pressure.mean()), 4)

    def branch(s):
        return {"sack": round(float(s.sack.mean()), 4),
                "scramble": round(float((s.qb_scramble == 1).mean()), 4),
                "throwaway": round(float((s.is_throw_away == True).mean()), 4)}  # noqa: E712

    # 패싱 다운(2nd·3rd·4th & 긴 거리)에서는 QB가 퍼스트다운 선까지 버티느라 색이 늘어난다 (M4에서 추가)
    T["dropback_branch"] = grouped_table(db, ["pressure", "passing_down", "blitz"], branch, MIN_N_RATE)

    # 커버리지·압박이 실제 던진 깊이를 바꾸는 비율 (E5)
    thrown = db[db.depth.notna()]
    base_mix = thrown.depth.value_counts(normalize=True)
    T["depth_ratio_cov"] = {c: {dp: round(float(thrown[thrown.covg == c].depth.value_counts(normalize=True).get(dp, 0)
                                               / base_mix[dp]), 3) for dp in DEPTHS} for c in COVERS}
    T["depth_ratio_pressure"] = {str(p): {dp: round(float(thrown[thrown.pressure == p].depth.value_counts(
        normalize=True).get(dp, 0) / base_mix[dp]), 3) for dp in DEPTHS} for p in (0, 1)}

    # ── 패스 결과 ────────────────────────────────────────────
    tgt = reg[reg.dropback & reg.depth.notna() & (reg.sack != 1) & (reg.qb_scramble != 1)
              & (reg.is_throw_away != True)].copy()  # noqa: E712 — 스로어웨이는 드롭백 분기에서 따로 처리
    tgt["zone2"] = np.where(tgt.zone.isin(["red", "goal"]), "red", "open")
    tgt["pressure"] = tgt.pressure.fillna(-1).astype(int)

    def pass_rates(s):
        return {"n": int(len(s)), "cmp": round(float(s.complete_pass.mean()), 4),
                "int": round(float(s.interception.mean()), 4)}

    T["pass_rates"] = grouped_table(tgt, ["depth", "passing_down", "pressure", "zone2", "pa", "covg"], pass_rates,
                                    MIN_N_RATE)
    comp = tgt[(tgt.complete_pass == 1) & (tgt.fumble != 1)]
    T["pass_air"] = grouped_table(comp, ["depth", "zone2", "pa", "covg"], lambda s: quantiles(s.air_yards), MIN_N_QUANT)
    T["pass_yac"] = grouped_table(comp[comp.yards_after_catch.notna()], ["depth", "zone2", "covg"],
                                  lambda s: quantiles(s.yards_after_catch), MIN_N_QUANT)
    T["catch_fumble_lost"] = round(float(tgt[tgt.complete_pass == 1].fumble_lost.mean()), 5)

    # ── 색·스크램블 야드 ─────────────────────────────────────
    T["sack_yards"] = quantiles(reg[(reg.sack == 1) & (reg.fumble != 1)].yards_gained)
    scr = reg[(reg.qb_scramble == 1) & (reg.fumble != 1)]
    T["scramble_yards"] = grouped_table(scr.assign(zone2=np.where(scr.zone.isin(["red", "goal"]), "red", "open")),
                                        ["zone2"], lambda s: quantiles(s.yards_gained), MIN_N_QUANT)
    T["sack_fumble_lost"] = round(float(reg[reg.sack == 1].fumble_lost.mean()), 5)

    # ── 런 결과 ──────────────────────────────────────────────
    rr = runs.copy()
    rr["box"] = rr.box.fillna("normal")
    rr["dd2"] = np.where(rr.dd.str.endswith("s"), "short", "std")

    def run_q(s):
        # 야드 분포는 펌블 없는 플레이로 만든다 (펌블은 엔진이 따로 판정; 펌블 리턴 야드가 꼬리를 왜곡함)
        clean = s[s.fumble != 1]
        return {"n": int(len(clean)), "q": quantiles(clean.yards_gained),
                "fumble_lost": round(float(s.fumble_lost.mean()), 5)}

    T["run"] = grouped_table(rr, ["rfam", "zone", "box", "dd2"], run_q, MIN_N_QUANT)
    return T


def build_special(cache: Path) -> dict:
    cols = ["season", "season_type", "play_type", "yardline_100", "kick_distance", "touchback", "return_yards",
            "field_goal_result", "roof", "extra_point_result", "two_point_attempt", "two_point_conv_result",
            "punt_blocked", "down", "ydstogo", "yards_gained", "first_down", "touchdown", "qb_dropback", "penalty",
            "fumble_lost", "interception"]
    frames = [pd.read_parquet(fetch(cache, f"pbp/play_by_play_{y}.parquet"), columns=cols) for y in PBP_SEASONS]
    d = pd.concat(frames, ignore_index=True)
    d = d[d.season_type == "REG"]
    S: dict = {}

    ko = d[(d.play_type == "kickoff") & d.season.isin(KICKOFF_SEASONS) & d.kick_distance.notna()]
    ko = ko[(ko.yardline_100 == 35)]
    S["kickoff_rows"] = [[int(65 - k), int(t), int(r) if not pd.isna(r) else 0]
                         for k, t, r in zip(ko.kick_distance, ko.touchback, ko.return_yards)]

    pu = d[(d.play_type == "punt") & d.kick_distance.notna() & (d.punt_blocked != 1)].copy()
    pu["bucket"] = pd.cut(pu.yardline_100, [0, 40, 50, 60, 70, 100], labels=["40", "50", "60", "70", "99"])
    S["punt_rows"] = {str(b): [[int(k), int(t), int(r) if not pd.isna(r) else 0]
                               for k, t, r in zip(g.kick_distance, g.touchback, g.return_yards)]
                      for b, g in pu.groupby("bucket", observed=True)}

    fg = d[(d.play_type == "field_goal") & d.kick_distance.notna()]
    from sklearn.isotonic import IsotonicRegression
    made = (fg.field_goal_result == "made").astype(int)
    iso = IsotonicRegression(increasing=False, y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(fg.kick_distance, made)
    S["fg_make_by_yard"] = {str(k): round(float(iso.predict([k])[0]), 4) for k in range(18, 71)}
    indoor = fg.roof.isin(["dome", "closed"])
    S["fg_indoor_bonus"] = round(float(made[indoor].mean() - made[~indoor].mean()), 4)
    S["fg_by_distance"] = {str(k): round(float(v), 3) for k, v in
                           fg.assign(b=(fg.kick_distance // 5 * 5)).groupby("b").apply(
                               lambda s: (s.field_goal_result == "made").mean()).items()}
    xp = d[d.play_type == "extra_point"]
    S["xp_rate"] = round(float((xp.extra_point_result == "good").mean()), 4)
    tp = d[d.two_point_attempt == 1]
    S["two_point_rate"] = round(float((tp.two_point_conv_result == "success").mean()), 4)

    # 3·4다운 전환율 (nfl4th 방식 go 판단의 기준값)
    conv = d[d.play_type.isin(["pass", "run"]) & d.down.isin([3, 4]) & (d.penalty != 1)]
    conv = conv.assign(tg=conv.ydstogo.clip(upper=15).astype(int))
    S["conversion_by_togo"] = {str(k): round(float(v), 3) for k, v in conv.groupby("tg").first_down.mean().items()}
    return S


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=DATA_DIR / "raw")
    ap.add_argument("--out", type=Path, default=DATA_DIR / "baseline")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    tables = build(args.cache, args.out)
    tables["special"] = build_special(args.cache)
    path = args.out / "tables.json"
    path.write_text(json.dumps(tables, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"저장: {path} ({path.stat().st_size / 1024:.0f} KB)")
    for k, v in tables.items():
        if isinstance(v, dict):
            print(f"  {k}: {len(v)} 칸")


if __name__ == "__main__":
    main()
