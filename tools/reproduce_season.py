"""시즌 재현 테스트와 β 배율 적합 (PRD M3 · ENGINE_DESIGN §5.5).

직전 3시즌 기록만으로 만든 능력치(`data/real/<시즌>/ratings.csv`)와 그 시즌 개막 로스터·뎁스차트로 정규시즌 전체를
여러 번 돌려 실제 결과와 비교한다. 부상·트레이드 등 시즌 중 변화는 반영하지 않는다 (개막 시점 예측).

비교 지표
- 팀 득실차 순위 상관 (스피어만 ρ), 공격 득점·수비 실점 순위 상관, 실제 공격·수비 EPA/플레이와의 상관
- 분산 비: 시즌 한 번 돌렸을 때 팀 경기당 득실차 표준편차 ÷ 실제 표준편차 (능력치 민감도 β의 크기를 정함)
- 경기 예측: 반복 시뮬 평균 점수차로 낸 홈 승률의 브라이어 점수·적중률, 같은 지표의 라스베이거스 스프레드(경기 직전 정보) 기준선

사용법: python tools/reproduce_season.py [--season 2025] [--reps 6] [--scales 0.75,1,1.5,2,2.5] [--workers 4]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import zlib
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean, pstdev

from gridiron.config import DATA_DIR

_LEAGUE = {}


def _league(season: int):
    if season not in _LEAGUE:
        from gridiron.data.real_league import load_real_league
        _LEAGUE[season] = load_real_league(season)
    return _LEAGUE[season]


def run_season(args: tuple[int, float, int, dict]) -> dict:
    season, scale, rep, center = args
    from gridiron.engine.adapter import build_team
    from gridiron.engine.norms import compute_norms
    from gridiron.engine.outcome.data_model import DataOutcome
    from gridiron.engine.skeleton.game import GameSim
    from gridiron.engine.skeleton.settings import GameSettings

    lg = _league(season)
    norms = compute_norms(lg)
    out = {}
    for g in lg.schedule:
        if g.game_type != "REG":
            continue
        seed = zlib.crc32(g.game_id.encode()) ^ (rep * 7919 + 13)
        res = GameSim([build_team(lg, g.home, 0, g.gameday), build_team(lg, g.away, 1, g.gameday)],
                      settings=GameSettings.from_config(), outcome=DataOutcome(beta_scale=scale, center=center),
                      seed=seed, norms=norms, neutral_site=g.neutral_site,
                      venue={"roof": g.roof, "surface": g.surface}).run()
        out[g.game_id] = (res["team"][0].stat["pts"], res["team"][1].stat["pts"])
    return {"scale": scale, "rep": rep, "games": out}


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    ra, rb = ranks(a), ranks(b)
    ma, mb = mean(ra), mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    return num / math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))


def real_results(season: int):
    games, teams = {}, defaultdict(lambda: {"pf": 0, "pa": 0, "g": 0})
    with (DATA_DIR / "real" / str(season) / "schedule.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["game_type"] != "REG" or not r["home_score"]:
                continue
            hs, as_ = int(float(r["home_score"])), int(float(r["away_score"]))
            spread = float(r["spread_line"]) if r["spread_line"] else 0.0
            games[r["game_id"]] = (r["home"], r["away"], hs, as_, spread)
            for t, pf, pa in ((r["home"], hs, as_), (r["away"], as_, hs)):
                teams[t]["pf"] += pf
                teams[t]["pa"] += pa
                teams[t]["g"] += 1
    return games, teams


def real_epa(season: int) -> dict[str, tuple[float, float]]:
    import pandas as pd
    p = pd.read_parquet(DATA_DIR / "raw" / f"play_by_play_{season}.parquet",
                        columns=["season_type", "posteam", "defteam", "epa", "play_type"])
    p = p[(p.season_type == "REG") & p.play_type.isin(["pass", "run"]) & p.epa.notna()]
    off = p.groupby("posteam").epa.mean()
    dfn = p.groupby("defteam").epa.mean()
    return {t: (float(off[t]), float(dfn[t])) for t in off.index}


def evaluate(season: int, runs: list[dict], real_games, real_teams, epa) -> dict:
    teams = sorted(real_teams)
    pf = defaultdict(list)
    pa = defaultdict(list)
    sd_per_rep = []
    margin = defaultdict(list)
    for run in runs:
        tot = defaultdict(lambda: [0, 0, 0])
        for gid, (h, a) in run["games"].items():
            if gid not in real_games:
                continue
            ht, at = real_games[gid][0], real_games[gid][1]
            tot[ht][0] += h; tot[ht][1] += a; tot[ht][2] += 1
            tot[at][0] += a; tot[at][1] += h; tot[at][2] += 1
            margin[gid].append(h - a)
        for t in teams:
            pf[t].append(tot[t][0] / tot[t][2])
            pa[t].append(tot[t][1] / tot[t][2])
        sd_per_rep.append(pstdev([(tot[t][0] - tot[t][1]) / tot[t][2] for t in teams]))
    sim_pd = [mean(pf[t]) - mean(pa[t]) for t in teams]
    real_pd = [(real_teams[t]["pf"] - real_teams[t]["pa"]) / real_teams[t]["g"] for t in teams]
    real_pf = [real_teams[t]["pf"] / real_teams[t]["g"] for t in teams]
    real_pa = [real_teams[t]["pa"] / real_teams[t]["g"] for t in teams]
    brier, hits, brier_vegas, hits_vegas, n = 0.0, 0, 0.0, 0, 0
    brier_rt, hits_rt = 0.0, 0
    power = dict(zip(teams, sim_pd))
    hfa = mean(mean(m) for m in margin.values())  # 시뮬 홈 이점 (점)
    for gid, (ht, at, hs, as_, spread) in real_games.items():
        if hs == as_ or gid not in margin:
            continue
        y = 1.0 if hs > as_ else 0.0
        # 반복 몇 번의 승패 비율은 0·1로 튀므로, 평균 점수차를 경기 잡음(σ 13.5점)으로 확률화한다
        p = 0.5 * (1 + math.erf(mean(margin[gid]) / (13.5 * math.sqrt(2))))
        pv = 0.5 * (1 + math.erf(spread / (13.5 * math.sqrt(2))))  # 스프레드 → 홈 승률 (σ 13.5점)
        # 전력차 방식: 시뮬 팀 득실차(전 경기·반복 평균) 차이 + 홈 이점 → 경기별 잡음이 거의 없다
        pr = 0.5 * (1 + math.erf((power[ht] - power[at] + hfa) / (13.5 * math.sqrt(2))))
        brier_rt += (pr - y) ** 2
        hits_rt += (pr > 0.5) == (y == 1.0)
        brier += (p - y) ** 2
        brier_vegas += (pv - y) ** 2
        hits += (p > 0.5) == (y == 1.0)
        hits_vegas += (pv > 0.5) == (y == 1.0)
        n += 1
    return {
        "league_ppg_sim": round(mean(mean(pf[t]) for t in teams), 2),
        "league_ppg_real": round(mean(real_pf), 2),
        "rho_point_diff": round(spearman(sim_pd, real_pd), 3),
        "rho_offense_points": round(spearman([mean(pf[t]) for t in teams], real_pf), 3),
        "rho_defense_points": round(spearman([mean(pa[t]) for t in teams], real_pa), 3),
        "rho_offense_epa": round(spearman([mean(pf[t]) for t in teams], [epa[t][0] for t in teams]), 3),
        "rho_defense_epa": round(spearman([mean(pa[t]) for t in teams], [epa[t][1] for t in teams]), 3),
        "sd_point_diff_sim_one_season": round(mean(sd_per_rep), 2),
        "sd_point_diff_real": round(pstdev(real_pd), 2),
        "sd_ratio": round(mean(sd_per_rep) / pstdev(real_pd), 3),
        "sd_true_talent_sim": round(pstdev(sim_pd), 2),
        "brier": round(brier / n, 4), "pick_rate": round(hits / n, 3),
        "brier_power": round(brier_rt / n, 4), "pick_rate_power": round(hits_rt / n, 3), "sim_home_edge": round(hfa, 2),
        "brier_vegas": round(brier_vegas / n, 4), "pick_rate_vegas": round(hits_vegas / n, 3),
        "teams": {t: {"sim_pd": round(s, 1), "real_pd": round(r, 1)} for t, s, r in zip(teams, sim_pd, real_pd)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2025)
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--scales", default="0.75,1,1.5,2,2.5")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--center-games", type=int, default=300)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    from gridiron.engine.calibration import measure_centers
    center = measure_centers(_league(args.season), args.center_games)
    print("center (이 시즌 능력치 분포로 측정):", center)
    real_games, real_teams = real_results(args.season)
    epa = real_epa(args.season)
    scales = [float(s) for s in args.scales.split(",")]
    jobs = [(args.season, s, r, center) for s in scales for r in range(args.reps)]
    with ProcessPoolExecutor(args.workers) as ex:
        runs = list(ex.map(run_season, jobs))
    results = {}
    for s in scales:
        res = evaluate(args.season, [r for r in runs if r["scale"] == s], real_games, real_teams, epa)
        results[str(s)] = res
        print(f"β×{s}: ρ득실차 {res['rho_point_diff']:+.2f}  ρ공격 {res['rho_offense_points']:+.2f}"
              f"  ρ수비 {res['rho_defense_points']:+.2f}  ρEPA(공/수) {res['rho_offense_epa']:+.2f}/{res['rho_defense_epa']:+.2f}"
              f"  분산비 {res['sd_ratio']:.2f}  득점 {res['league_ppg_sim']}/{res['league_ppg_real']}"
              f"  브라이어 경기별 {res['brier']:.3f}·전력차 {res['brier_power']:.3f} (베가스 {res['brier_vegas']:.3f})"
              f"  적중 {res['pick_rate']:.3f}·{res['pick_rate_power']:.3f} (베가스 {res['pick_rate_vegas']:.3f})")
    if args.out:
        args.out.write_text(json.dumps({"season": args.season, "reps": args.reps, "center": center,
                                        "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
