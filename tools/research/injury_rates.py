"""실측 부상률·부위·결장 기간 (PRD F10-1·F10-2, M5b) → data/baseline/injuries.json.

정의 (2021–2025 정규시즌):
- 부상 사건: 직전 팀 경기에 뛴 선수가 이번 주 공식 부상 리포트에 부상(질병·개인 사유 제외)으로 처음 오른 경우.
- 결장 경기: 사건 주부터 다시 스냅을 기록할 때까지 팀 경기 수. 시즌 안에 돌아오지 못하면 시즌 아웃(-1).
- 리포트 누락 보정: 부상 리포트 없이 IR로 바로 가는 시즌 아웃 부상이 있다. 직전 경기 50% 이상 뛴 선수가
  리포트 없이 시즌 끝까지(4경기 이상 남은 상태로) 사라진 경우를 "리포트 밖 시즌 아웃"으로 센다 (방출·트레이드가 섞여 상한값).
- 발생률: 사건 수 ÷ 포지션별 총 스냅(공격+수비+특수팀) = 스냅당 위험.

    python tools/research/injury_rates.py --cache data/raw
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

PART = {"Knee": "knee", "Ankle": "ankle", "Hamstring": "hamstring", "Shoulder": "shoulder", "Concussion": "concussion",
        "Groin": "groin", "Calf": "calf", "Foot": "foot", "Back": "back", "Hip": "hip", "Neck": "neck",
        "Quadricep": "thigh", "Thigh": "thigh", "Toe": "toe", "Elbow": "arm", "Ribs": "ribs", "Rib": "ribs",
        "Chest": "ribs", "Abdomen": "ribs", "Oblique": "ribs", "Hand": "hand", "Wrist": "hand", "Thumb": "hand",
        "Finger": "hand", "Fingers": "hand", "Pectoral": "pectoral", "Achilles": "achilles", "Heel": "foot",
        "Forearm": "arm", "Biceps": "arm", "Triceps": "arm", "Knees": "knee", "Ankles": "ankle", "Shin": "calf",
        "Head": "concussion", "Illness": None}
LONG = 8          # 이 이상 결장은 "장기·시즌 아웃" 한 칸으로 묶는다
GROUP = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "T": "OL", "G": "OL", "C": "OL", "OT": "OL",
         "OG": "OL", "OL": "OL", "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "LB": "LB", "ILB": "LB", "OLB": "LB",
         "MLB": "LB", "CB": "DB", "DB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "SAF": "DB", "K": "K", "P": "K",
         "LS": "K"}


def part_of(x) -> str | None:
    if not isinstance(x, str) or "not injury" in x.lower() or "rest" in x.lower() or "personal" in x.lower():
        return None
    first = x.replace(",", " ").split()[0].strip().title() if x.strip() else ""
    for k, v in PART.items():
        if x.strip().title().startswith(k):
            return v
    return {"Illness": None}.get(first, "other")


def build(cache: Path, seasons: range) -> dict:
    sc = pd.read_parquet(cache / "snap_counts.parquet")
    sc = sc[(sc.game_type == "REG") & sc.season.isin(seasons)]
    ids = pd.read_parquet(cache / "players.parquet", columns=["gsis_id", "pfr_id"]).dropna().drop_duplicates("pfr_id")
    sc = sc.merge(ids, left_on="pfr_player_id", right_on="pfr_id", how="inner")
    sc["snaps"] = sc.offense_snaps.fillna(0) + sc.defense_snaps.fillna(0) + sc.st_snaps.fillna(0)
    sc["pct"] = np.maximum(sc.offense_pct.fillna(0), sc.defense_pct.fillna(0))
    sc["grp"] = sc.position.map(GROUP)
    sc = sc[sc.snaps > 0]
    team_weeks = sc.groupby(["season", "team"]).week.apply(lambda s: sorted(set(s))).to_dict()
    played = {(r.season, r.gsis_id, r.week): r for r in sc[["season", "gsis_id", "week", "team", "pct", "grp"]].itertuples()}
    snaps_by_grp = sc.groupby("grp").snaps.sum().to_dict()

    inj = pd.read_parquet(cache / "injuries.parquet")
    inj = inj[(inj.game_type == "REG") & inj.season.isin(seasons) & inj.report_status.isin(["Out", "Doubtful", "Questionable"])]
    inj = inj.assign(part=inj.report_primary_injury.map(part_of), week=inj.week.astype(int), season=inj.season.astype(int))
    inj = inj[inj.part.notna()]
    on_report = set(zip(inj.season, inj.gsis_id, inj.week))

    def missed(season, team, pid, week) -> tuple[int, int]:
        """(결장 경기 수, 남은 경기 수). 시즌 안에 못 돌아오면 결장 = -1."""
        weeks = [w for w in team_weeks.get((season, team), []) if w >= week]
        for n, w in enumerate(weeks):
            if (season, pid, w) in played:
                return n, len(weeks)
        return -1, len(weeks)

    events = []
    for r in inj.sort_values("week").itertuples():
        weeks = team_weeks.get((r.season, r.team), [])
        prev = [w for w in weeks if w < r.week]
        if not prev or (r.season, r.gsis_id, prev[-1]) not in played or (r.season, r.gsis_id, prev[-1]) in on_report:
            continue
        g = GROUP.get(r.position) or played[(r.season, r.gsis_id, prev[-1])].grp
        m, left = missed(r.season, r.team, r.gsis_id, r.week)
        if m < 0 and left < LONG:
            m = -2                     # 중도절단 (돌아오기 전에 시즌 끝) → 기간 분포에서 뺀다
        elif m < 0 or m >= LONG:
            m = LONG                   # 장기(8경기+) 또는 시즌 아웃
        events.append({"season": r.season, "part": r.part, "grp": g, "missed": m, "status": r.report_status})

    # 리포트 밖 시즌 아웃 (상한 추정): 50%+ 뛰고, 4경기 이상 남았는데 시즌 끝까지 안 뛰고, 리포트에도 없음
    reported = {(s, p) for s, p, _ in on_report}
    silent = Counter()
    last_game = sc.sort_values("week").groupby(["season", "gsis_id"]).tail(1)
    for r in last_game.itertuples():
        weeks = team_weeks[(r.season, r.team)]
        left = [w for w in weeks if w > r.week]
        if len(left) >= 4 and r.pct >= 0.5 and (r.season, r.gsis_id) not in reported:
            silent[r.grp] += 1

    ev = pd.DataFrame(events)
    n_team_games = sum(len(v) for v in team_weeks.values())
    out = {"seasons": [seasons.start, seasons.stop - 1], "team_games": n_team_games, "events": len(ev),
           "per_team_game": round(len(ev) / n_team_games, 3),
           "silent_season_ending_per_team_game": round(sum(silent.values()) / n_team_games, 4)}
    out["hazard_per_snap"] = {g: round((ev.grp == g).sum() / snaps_by_grp[g], 6) for g in sorted(snaps_by_grp) if g}
    out["silent_hazard_per_snap"] = {g: round(silent[g] / snaps_by_grp[g], 7) for g in sorted(snaps_by_grp) if g}
    parts = {}
    for part, d in ev.groupby("part"):
        m = d.missed.to_numpy()
        m = m[m >= 0]
        hist = Counter(int(x) for x in m)
        parts[part] = {"share": round(len(d) / len(ev), 4), "n": int(len(d)),
                       "missed_hist": {str(k): int(v) for k, v in sorted(hist.items())},
                       "mean_missed_returned": round(float(m[m < LONG].mean()), 2),
                       "season_ending": round(float((m >= LONG).mean()), 3),
                       "by_group": {g: round(float((d.grp == g).sum() / (ev.grp == g).sum()), 4)
                                    for g in sorted(ev.grp.dropna().unique())}}
    out["parts"] = parts
    m = ev.missed.to_numpy()
    m = m[m >= 0]
    out["long"] = LONG
    out["missed_overall"] = {"zero": round(float((m == 0).mean()), 3), "one_three": round(float(((m >= 1) & (m <= 3)).mean()), 3),
                             "four_seven": round(float(((m >= 4) & (m < LONG)).mean()), 3),
                             "long": round(float((m >= LONG).mean()), 3), "mean": round(float(m.mean()), 2)}
    out["status_share"] = ev.status.value_counts(normalize=True).round(3).to_dict()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/raw")
    ap.add_argument("--out", default="data/baseline/injuries.json")
    a = ap.parse_args()
    res = build(Path(a.cache), range(2021, 2026))
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "parts"}, ensure_ascii=False, indent=1))
    for p, d in sorted(res["parts"].items(), key=lambda kv: -kv[1]["share"]):
        print(f"{p:<11} {d['share']:.3f}  복귀 평균 {d['mean_missed_returned']:.2f}경기  시즌아웃 {d['season_ending']:.3f}")


if __name__ == "__main__":
    main()
