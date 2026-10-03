"""전술 관련 실측 데이터 (ENGINE_DESIGN §4·§6, PRD F4·F11-3e, M4).

1. 상성표 `data/baseline/payoff.json`
   - 패스: 실제 던진 깊이 × 커버리지 × 블리츠 → 드롭백 EPA (색·스크램블 포함 기대값)
   - 런: 패밀리 × 박스 → EPA
   코디네이터가 "이 상황에서 이 콜이 얼마나 좋은가"를 가늠하는 데 쓴다. 관측값이므로 인과 효과가 아니라
   상대적 순서의 근거로만 쓰고, 콜 확률은 실측 정체성 분포를 기울이는 방식으로만 바꾼다 (§6.4 구현 노트).
2. 팀 성향 `data/real/<시즌+1>/team_tendencies.json`
   - 공격: 기대 대비 패스 비율(PROE), 플레이액션·스크린·딥 비율, 아웃사이드 런 비율, 퍼스넬 비중
   - 수비: 블리츠율, 맨 커버리지 비율, 커버리지 쉘 분포, 헤비·라이트 박스 비율
   AI 팀 기본 전술, 숙련도 시작값(F11-3e), 1주차 스카우팅 사전값(§6.3)에 쓴다.

    python -m gridiron.baseline.tactics_data --cache data/raw --season 2025
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import DATA_DIR
from .build import BOXES, COVERS, DEPTHS, PART_SEASONS, load

MAN = {"C0", "C1", "2M"}


def payoff(d: pd.DataFrame) -> dict:
    reg = d[(d.season_type == "REG") & d.season.isin(PART_SEASONS) & d.epa.notna()]
    db = reg[reg.dropback & reg.covg.notna()]
    att = db[db.depth.notna()]
    non = db[db.depth.isna()]  # 색·스크램블 등 송구 없는 드롭백
    out: dict = {"pass": {}, "run": {}, "n": {}}
    league_att = att.groupby("depth").epa.mean()
    for depth in DEPTHS:
        out["pass"][depth] = {}
        for cov in COVERS:
            out["pass"][depth][cov] = {}
            for blitz in (0, 1):
                a = att[(att.depth == depth) & (att.covg == cov) & (att.blitz == blitz)]
                n = non[(non.covg == cov) & (non.blitz == blitz)]
                tot = len(db[(db.covg == cov) & (db.blitz == blitz)])
                # 표본이 적은 칸은 깊이 평균 쪽으로 수축 (가상 표본 200)
                e_att = (a.epa.sum() + 200 * league_att[depth]) / (len(a) + 200)
                r_non = len(n) / max(tot, 1)
                e_non = n.epa.mean() if len(n) else non.epa.mean()
                out["pass"][depth][cov][str(blitz)] = round(float((1 - r_non) * e_att + r_non * e_non), 4)
    runs = reg[(reg.kind == "run") & reg.rfam.isin(["inside", "outside"]) & reg.box.notna()]
    for fam in ("inside", "outside"):
        out["run"][fam] = {b: round(float(runs[(runs.rfam == fam) & (runs.box == b)].epa.mean()), 4) for b in BOXES}
    out["n"] = {"dropbacks": int(len(db)), "runs": int(len(runs))}
    return out


def tendencies(d: pd.DataFrame, season: int) -> dict:
    s = d[(d.season == season) & (d.season_type == "REG")]
    normal = s[s.wp.between(0.1, 0.9) & s.xpass.notna()]
    teams = {}
    lg = {}

    def rates(off: pd.DataFrame, dfn: pd.DataFrame) -> dict:
        db = off[off.dropback]
        att = db[db.depth.notna()]
        runs = off[(off.kind == "run") & off.rfam.isin(["inside", "outside"])]
        early_run = dfn[(dfn.kind == "run") & dfn.dd.isin(["1st", "2m", "2l"]) & dfn.box.notna()]
        cov = dfn[dfn.dropback & dfn.covg.notna()]
        pers = off[off.pers.notna() & (off.pers != "other")]
        return {
            "offense": {
                "proe": round(float((off.dropback.astype(float) - off.xpass).mean()), 4),
                "pa_rate": round(float(att[att.depth != "screen"].pa.mean()), 4),
                "screen_rate": round(float((att.depth == "screen").mean()), 4),
                "deep_rate": round(float((att.depth == "deep").mean()), 4),
                "outside_run": round(float((runs.rfam == "outside").mean()), 4),
                "personnel": {k: round(float(v), 4) for k, v in pers.pers.value_counts(normalize=True).items()},
            },
            "defense": {
                "blitz_rate": round(float(cov.blitz.mean()), 4),
                "man_rate": round(float(cov.covg.isin(MAN).mean()), 4),
                "coverage": {k: round(float(v), 4) for k, v in cov.covg.value_counts(normalize=True).items()},
                "heavy_box": round(float((early_run.box == "heavy").mean()), 4),
                "light_box": round(float((early_run.box == "light").mean()), 4),
            },
        }

    for team in sorted(set(s.posteam.dropna())):
        teams[team] = rates(normal[normal.posteam == team], s[s.defteam == team])
    lg = rates(normal, s)
    return {"season": season, "league": lg, "teams": teams}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=DATA_DIR / "raw")
    ap.add_argument("--season", type=int, default=2025, help="성향을 측정할 시즌 (다음 시즌 폴더에 저장)")
    args = ap.parse_args()
    d = load(args.cache)
    po = payoff(d)
    (DATA_DIR / "baseline" / "payoff.json").write_text(json.dumps(po, separators=(",", ":")), encoding="utf-8")
    out_dir = DATA_DIR / "real" / str(args.season + 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    tend = tendencies(d, args.season)
    (out_dir / "team_tendencies.json").write_text(json.dumps(tend, ensure_ascii=False, indent=1), encoding="utf-8")
    print("상성표 (패스 깊이 × 커버리지, 블리츠 없음/있음):")
    for depth in DEPTHS:
        print(f"  {depth:6s}", "  ".join(f"{c}:{po['pass'][depth][c]['0']:+.2f}/{po['pass'][depth][c]['1']:+.2f}"
                                          for c in COVERS))
    print("런 × 박스:", po["run"])
    lg = tend["league"]
    print("리그 성향:", json.dumps(lg, ensure_ascii=False)[:400])
    print("PROE 범위:", min(t["offense"]["proe"] for t in tend["teams"].values()),
          max(t["offense"]["proe"] for t in tend["teams"].values()), "/ 블리츠율",
          min(t["defense"]["blitz_rate"] for t in tend["teams"].values()),
          max(t["defense"]["blitz_rate"] for t in tend["teams"].values()), "/ 맨 비율",
          min(t["defense"]["man_rate"] for t in tend["teams"].values()),
          max(t["defense"]["man_rate"] for t in tend["teams"].values()))
    _ = np  # numpy는 load에서 사용


if __name__ == "__main__":
    main()
