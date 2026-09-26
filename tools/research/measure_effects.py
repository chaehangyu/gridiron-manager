"""실제 NFL 데이터로 엔진 설계용 효과 크기를 측정한다.

nflverse의 2023–2025 play-by-play, 참여 데이터(participation), FTN 차팅을 받아
플레이 단위로 합친 뒤, 엔진 설계서(docs/ENGINE_DESIGN.md §1)의 표를 다시 계산한다.

사용법:
    pip install pandas pyarrow
    python tools/research/measure_effects.py --cache data/raw

주의: 관측 데이터이므로 인과 효과가 아니라 "보정 목표"로만 쓴다.
"""
from __future__ import annotations

import argparse
import re
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
SEASONS = (2023, 2024, 2025)
PBP_COLS = [
    "game_id", "play_id", "season", "season_type", "play_type", "posteam", "defteam",
    "epa", "success", "xpass", "pass_oe", "run_gap", "run_location", "air_yards",
    "qb_scramble", "qb_dropback", "sack", "down", "ydstogo", "yardline_100", "wp",
]
COVERS = ["COVER_0", "COVER_1", "2_MAN", "COVER_2", "COVER_3", "COVER_4", "COVER_6", "COVER_9"]


def fetch(cache: Path, rel: str) -> Path:
    dst = cache / Path(rel).name
    if not dst.exists():
        cache.mkdir(parents=True, exist_ok=True)
        print(f"download {rel}")
        urllib.request.urlretrieve(f"{BASE}/{rel}", dst)
    return dst


def load(cache: Path) -> pd.DataFrame:
    frames = []
    for y in SEASONS:
        pb = pd.read_parquet(fetch(cache, f"pbp/play_by_play_{y}.parquet"), columns=PBP_COLS)
        pa = pd.read_parquet(fetch(cache, f"pbp_participation/pbp_participation_{y}.parquet"))[
            ["nflverse_game_id", "play_id", "offense_personnel", "defenders_in_box",
             "was_pressure", "defense_man_zone_type", "defense_coverage_type", "time_to_throw"]]
        ft = pd.read_parquet(fetch(cache, f"ftn_charting/ftn_charting_{y}.parquet"))[
            ["nflverse_game_id", "nflverse_play_id", "n_defense_box", "is_play_action",
             "is_screen_pass", "n_blitzers", "is_qb_sneak"]]
        d = pb.merge(pa, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "play_id"], how="left")
        d = d.merge(ft, left_on=["game_id", "play_id"], right_on=["nflverse_game_id", "nflverse_play_id"],
                    how="left", suffixes=("", "_ftn"))
        frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    # 승부가 이미 기운 상황(승률 5% 미만·95% 초과)은 제외
    d = d[d.play_type.isin(["pass", "run"]) & d.epa.notna() & d.wp.between(0.05, 0.95)].copy()
    d["dropback"] = d.qb_dropback == 1
    d["designed_run"] = (d.play_type == "run") & (d.qb_scramble != 1)
    d["family"] = d.apply(family, axis=1)
    d["box"] = d.n_defense_box.fillna(d.defenders_in_box)
    d["blitz"] = d.n_blitzers.fillna(0) >= 1
    d["pers"] = d.offense_personnel.map(personnel)
    return d.reset_index(drop=True)


def family(r) -> str:
    if r.designed_run:
        if r.is_qb_sneak is True:
            return "qb_sneak"
        return "run_inside" if (r.run_gap == "guard" or r.run_location == "middle") else "run_outside"
    if r.is_screen_pass is True:
        return "screen"
    prefix = "pa_" if r.is_play_action is True else ""
    a = r.air_yards
    if pd.isna(a):
        return prefix + "dropback_na"
    return prefix + ("quick" if a <= 5 else "inter" if a <= 15 else "deep")


def personnel(s) -> str | None:
    if not isinstance(s, str):
        return None
    rb = re.search(r"(\d) RB", s)
    te = re.search(r"(\d) TE", s)
    return f"{rb.group(1) if rb else 0}{te.group(1) if te else 0}"


def show(title: str, df) -> None:
    print(f"\n## {title}\n{df}")


def agg(g):
    return g.agg(n=("epa", "size"), epa=("epa", "mean"), success=("success", "mean")).round(3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path("data/raw"))
    d = load(ap.parse_args().cache)
    pd.set_option("display.width", 200)
    print(f"plays: {len(d)}")

    neutral = d[d.down.isin([1, 2]) & d.ydstogo.between(4, 10) & d.yardline_100.between(20, 80)]
    runs = neutral[neutral.family.isin(["run_inside", "run_outside"])]
    runs = runs.assign(boxb=pd.cut(runs.box, [0, 5, 6, 7, 8, 11], labels=["<=5", "6", "7", "8", "9+"]))
    show("E1 런 × 박스 인원 (1·2다운, 4–10야드, 양 20야드선 사이)", agg(runs.groupby(["family", "boxb"], observed=True)))

    db = neutral[neutral.dropback]
    show("E2 드롭백 × 압박", agg(db.groupby("was_pressure")))
    show("E3 드롭백 × 블리츠", agg(db.groupby("blitz")))
    show("E3b 스크린 × 블리츠", agg(neutral[neutral.family == "screen"].groupby("blitz")))

    mid = d[d.down.isin([1, 2, 3]) & d.yardline_100.between(20, 80) & d.dropback]
    show("E4 압박률·색 비율 × 블리츠", mid.groupby("blitz").agg(
        n=("epa", "size"), pressure=("was_pressure", "mean"), sack=("sack", "mean")).round(3))

    c = mid[mid.defense_coverage_type.isin(COVERS)].copy()
    c["cov"] = c.defense_coverage_type.replace({"COVER_4": "QUARTERS", "COVER_6": "QUARTERS", "COVER_9": "QUARTERS"})
    c["depth"] = c.family.str.replace("pa_", "", regex=False).replace({"dropback_na": "sack/scramble"})
    show("E5 커버리지별 실제 던진 깊이 (행 %)", (pd.crosstab(c["cov"], c.depth, normalize="index") * 100).round(1))
    show("E6 커버리지별 압박·색·EPA·송구 시간", c.groupby("cov").agg(
        n=("epa", "size"), pressure=("was_pressure", "mean"), sack=("sack", "mean"),
        epa=("epa", "mean"), time_to_throw=("time_to_throw", "mean")).round(3))
    show("E7 던진 깊이 × 커버리지 EPA (조건부: QB가 읽고 던진 뒤)",
         c[c.depth.isin(["quick", "inter", "deep", "screen"])].pivot_table(
             index="depth", columns="cov", values="epa", aggfunc="mean").round(3))
    show("E8 던진 깊이 × 압박 EPA", c.pivot_table(index="depth", columns="was_pressure", values="epa", aggfunc="mean").round(3))

    e = d[d.down.isin([1, 2]) & d.yardline_100.between(20, 80) & d.xpass.notna()]
    e = e.assign(xb=pd.cut(e.xpass, [0, .4, .55, .7, 1], labels=["<.40", ".40-.55", ".55-.70", ">.70"]),
                 kind=np.where(e.dropback, "dropback", "run"))
    show("E9 예상 밖 플레이: 기대 패스 확률 구간별 효율 (1·2다운)", agg(e.groupby(["kind", "xb"], observed=True)))

    f = d[(d.down == 1) & (d.ydstogo == 10) & d.yardline_100.between(20, 80)]
    show("E10 1st & 10 퍼스넬별 런 비율·박스·EPA", f.groupby("pers").agg(
        n=("epa", "size"), run_rate=("designed_run", "mean"), box=("box", "mean"), epa=("epa", "mean"))
        .query("n > 400").round(3))
    show("E10b 퍼스넬 × 런/패스 EPA", f[f.pers.isin(["11", "12", "13"])].groupby(["pers", "designed_run"]).agg(
        n=("epa", "size"), epa=("epa", "mean"), box=("box", "mean")).round(3))

    pa = neutral[neutral.dropback].assign(pa=lambda z: z.family.str.startswith("pa_"))
    show("E11 플레이액션 × 박스", agg(pa.groupby(["pa", pd.cut(pa.box, [0, 6, 7, 11], labels=["<=6", "7", "8+"])], observed=True)))
    show("E12 맨 vs 존", agg(db[db.defense_man_zone_type.isin(["MAN_COVERAGE", "ZONE_COVERAGE"])].groupby("defense_man_zone_type")))

    reg = d[d.season_type == "REG"]
    off = reg.groupby(["season", "posteam"]).agg(epa=("epa", "mean"), proe=("pass_oe", "mean"))
    blz = reg[reg.dropback].groupby(["season", "defteam"]).blitz.mean()
    man = reg[reg.dropback & reg.defense_man_zone_type.isin(["MAN_COVERAGE", "ZONE_COVERAGE"])] \
        .groupby(["season", "defteam"]).defense_man_zone_type.apply(lambda s: (s == "MAN_COVERAGE").mean())
    print("\n## E13 팀 간 차이 (팀-시즌 단위)")
    print(f"공격 EPA/플레이 표준편차 {off.epa.std():.3f}")
    print(f"기대 대비 패스 비율(PROE) 표준편차 {off.proe.std():.1f}%p, 범위 {off.proe.min():.1f}~{off.proe.max():.1f}")
    print(f"블리츠율 범위 {blz.min():.2f}~{blz.max():.2f}, 맨 커버리지율 범위 {man.min():.2f}~{man.max():.2f}")


if __name__ == "__main__":
    main()
