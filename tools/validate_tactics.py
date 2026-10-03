"""M4 엔진 검증 T1–T9 (ENGINE_DESIGN §11).

실제 2026 리그(환경변수 GRIDIRON_VALIDATE_LEAGUE=sample이면 샘플 리그)의 전력이 리그 중앙에 가까운 두 팀(X·Y)에
전술·숙련도·능력치 변형을 걸어 경기를 반복하고, 중계 이벤트로 플레이별 EPA를 계산한다. 팀의 실측 성향 전술 대신
테스트마다 정한 전술을 쓴다 (기본은 리그 평균 전술).
실측 비교값(T1·T2)은 nflverse 원시 데이터(data/raw)에서 같은 정의로 계산한다.

사용법: python tools/validate_tactics.py [t1 t2 … t9 | all] [--scale 1.0] [--workers 4] [--out data/baseline/m4_validation.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean

from gridiron.config import DATA_DIR

_L = {}
X, Y = None, None


SOURCE = os.environ.get("GRIDIRON_VALIDATE_LEAGUE", "real:2026")   # 게임과 같은 실제 리그 (sample도 가능)


def league():
    if "L" not in _L:
        from gridiron.engine.norms import compute_norms
        if SOURCE == "sample":
            from gridiron.data.sample import generate_sample_league
            lg = generate_sample_league(seed=7)
        else:
            from gridiron.data.real_league import load_real_league
            lg = load_real_league(int(SOURCE.split(":")[1]))
            lg.schedule = [g for g in lg.schedule if g.game_type == "REG"]
        _L["L"], _L["N"] = lg, compute_norms(lg)
    return _L["L"], _L["N"]


def pair() -> tuple[str, str]:
    """평균 주전 PR이 리그 중앙값에 가장 가까운 두 팀."""
    from gridiron.ratings.position_rating import position_rating
    lg, _ = league()
    score = {}
    for abbr, t in lg.teams.items():
        ids = {pid for ids in t.depth_chart.values() for pid in ids[:1]}
        score[abbr] = mean(position_rating(lg.players[i]) for i in ids if i in lg.players)
    med = sorted(score.values())[len(score) // 2]
    a, b = sorted(score, key=lambda k: abs(score[k] - med))[:2]
    return a, b


# ── 능력치 변형 ───────────────────────────────────────────────────
MODS = {
    "strong_ol": {"OL": {"strength": 18.5, "agility": 6.0, "speed": 3.0}},
    "agile_ol": {"OL": {"strength": 9.0, "agility": 15.0, "speed": 8.0}},
    "man_cb": {"CB": {"man_coverage": 17.5, "press": 17.0, "speed": 17.0, "agility": 16.0, "zone_coverage": 8.0,
                      "football_iq": 8.0, "ball_skills": 9.0, "acceleration": 11.0}},
    "elite_run": {"OL": {"run_block": "+4"}, "RB": {"vision": "+4", "elusiveness": "+4", "break_tackle": "+4"},
                  "QB": {"short_accuracy": "-4", "medium_accuracy": "-4", "deep_accuracy": "-4", "decision": "-3"}},
}


def apply_mod(team_sim, mod: str) -> None:
    for p in team_sim.players:
        for k, v in MODS[mod].get(p.pos, {}).items():
            if isinstance(v, str):
                p.attributes[k] = max(1.0, min(20.0, p.attributes[k] + float(v)))
            else:
                p.attributes[k] = v


# ── EPA ──────────────────────────────────────────────────────────
def epa_records(events, abbrs) -> list[dict]:
    out = []
    i, n = 0, len(events)
    while i < n:
        e = events[i]
        if e["type"] != "clock" or e.get("playType") not in ("pass", "run") or e.get("ep") is None:
            i += 1
            continue
        j = i + 1
        play = {}
        score = None
        while j < n and events[j]["type"] != "clock":
            ev = events[j]
            for k, v in ev.items():
                if k.startswith("x_"):
                    play[k[2:]] = v
            if ev.get("td"):
                score = 7 if ev.get("t") == e["t"] else -7
            if ev.get("safety"):
                score = -2
            if ev["type"] in ("interception", "fumble") and "turnover" not in play:
                play["turnover"] = ev["type"]
            if ev["type"] == "penalty":
                play["penalty"] = True
            if ev["type"] in ("passComplete", "passIncomplete", "interception", "sack", "run"):
                play.setdefault("res", "scramble" if ev["type"] == "run" and ev.get("scramble") else ev["type"])
            j += 1
        nxt = events[j] if j < n else None
        if score is not None:
            epa = score - e["ep"]
        elif nxt is not None and nxt.get("ep") is not None:
            epa = (nxt["ep"] if nxt["t"] == e["t"] else -nxt["ep"]) - e["ep"]
        else:
            i = j
            continue
        play.update({"o": abbrs[e["t"]], "kind": e["playType"], "q": e["quarter"], "epa": epa,
                     "down": e["down"], "togo": e["toGo"], "yl": 100 - e["scrimmage"]})
        out.append(play)
        i = j
    return out


def run_job(spec: dict) -> dict:
    from gridiron.engine.adapter import build_team
    from gridiron.engine.outcome.data_model import DataOutcome
    from gridiron.engine.skeleton.game import GameSim
    from gridiron.engine.skeleton.settings import GameSettings
    from gridiron.tactics.model import Tactics

    lg, N = league()
    plays, results = [], []
    t0 = time.time()
    for k, seed in enumerate(spec["seeds"]):
        a, b = spec["teams"]
        if spec.get("swap", True) and k % 2:
            a, b = b, a
        teams = [build_team(lg, a, 0, lg.season_start()), build_team(lg, b, 1, lg.season_start())]
        for ts in teams:
            if spec.get("neutral", True):
                ts.tactics = Tactics()            # 비교 실험은 리그 평균 전술·기본 숙련도(80)에서 시작
                ts.familiarity = {}
            if ts.abbr in spec.get("tac", {}):
                ts.tactics = Tactics.from_dict(spec["tac"][ts.abbr])
            if ts.abbr in spec.get("fam", {}):
                ts.familiarity = {**ts.familiarity, **spec["fam"][ts.abbr]}
            for m in spec.get("mods", {}).get(ts.abbr, []):
                apply_mod(ts, m)
            ts.ai_controlled = spec.get("ai", True)
        sim = GameSim(teams, settings=GameSettings.from_config(), seed=seed, norms=N,
                      outcome=DataOutcome.for_league(lg, learning=spec.get("learning", True),
                                                     explain=spec.get("explain", False),
                                                     situation_shift=spec.get("situ")),
                      do_play_by_play=spec.get("pbp", True))
        res = sim.run()
        results.append({t.abbr: t.stat["pts"] for t in res["team"]})
        if spec.get("pbp", True):
            plays += epa_records(res["playByPlay"], [teams[0].abbr, teams[1].abbr])
    return {"plays": plays, "results": results, "secs": time.time() - t0}


def run_many(pool, specs: list[dict]) -> list[dict]:
    return list(pool.map(run_job, specs))


def chunks(spec: dict, games: int, parts: int, base: int) -> list[dict]:
    seeds = list(range(base, base + games))
    return [{**spec, "seeds": seeds[i::parts]} for i in range(parts)]


def merge(outs: list[dict]) -> dict:
    return {"plays": [p for o in outs for p in o["plays"]], "results": [r for o in outs for r in o["results"]],
            "secs": sum(o["secs"] for o in outs)}


def m(xs) -> float:
    xs = list(xs)
    return round(mean(xs), 4) if xs else float("nan")


def se(xs) -> float:
    xs = list(xs)
    if len(xs) < 2:
        return float("nan")
    mu = mean(xs)
    return round(math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1) / len(xs)), 4)


# ── 실측 비교값 ──────────────────────────────────────────────────
def ours_epa(seasons) -> "pd.DataFrame":
    """실측 플레이의 EPA를 **엔진과 같은 EP 모델**로 다시 계산한다 (nflverse EP와 시간·점수 특징이 달라 기울기가 다르다)."""
    import numpy as np
    import pandas as pd
    from gridiron.engine import models_ml as M
    frames = []
    for y in seasons:
        d = pd.read_parquet(DATA_DIR / "raw" / f"play_by_play_{y}.parquet",
                            columns=["game_id", "play_id", "season_type", "play_type", "posteam", "down", "ydstogo",
                                     "yardline_100", "touchdown", "td_team", "safety", "game_half", "qtr",
                                     "score_differential", "half_seconds_remaining"])
        d = d[(d.season_type == "REG") & d.down.notna() & d.posteam.notna() & d.yardline_100.between(1, 99)]
        d = d.sort_values(["game_id", "play_id"])
        d["ep_o"] = [M.ep(int(a), float(b), float(c)) for a, b, c in zip(d.down, d.ydstogo, d.yardline_100)]
        g = d.groupby(["game_id", "game_half"])
        d["nxt"], d["nxt_team"] = g.ep_o.shift(-1), g.posteam.shift(-1)
        d["epa"] = np.where(d.touchdown == 1, np.where(d.td_team == d.posteam, 7, -7) - d.ep_o,
                            np.where(d.safety == 1, -2 - d.ep_o,
                                     np.where(d.nxt_team == d.posteam, d.nxt - d.ep_o, -d.nxt - d.ep_o)))
        from gridiron.engine.ai.coordinator import game_state
        d["gs"] = [game_state(s, h, q >= 3) for s, h, q in zip(d.score_differential.fillna(0),
                                                                d.half_seconds_remaining.fillna(900), d.qtr.fillna(1))]
        frames.append(d[["game_id", "play_id", "epa", "gs"]])
    return pd.concat(frames)


def real_effects() -> dict:
    import pandas as pd
    from gridiron.baseline.build import PART_SEASONS, load
    d = load(DATA_DIR / "raw")
    d = d[d.season_type == "REG"].drop(columns=["epa"]).merge(ours_epa(PART_SEASONS), on=["game_id", "play_id"])
    d = d[d.epa.notna() & d.season.isin(PART_SEASONS)]
    early = d[d.down.isin([1, 2]) & d.wp.between(0.1, 0.9)]
    part = d[d.season.isin(PART_SEASONS)]
    runs = early[(early.kind == "run") & early.box.notna() & (early.qb_scramble != 1)]
    db = part[part.dropback]
    att = db[db.depth.notna() & db.covg.notna()]
    out = {
        "run_epa_by_box": {b: round(float(runs[runs.box == b].epa.mean()), 3) for b in ("light", "normal", "heavy")},
        "dropback_epa_pressure": {str(k): round(float(v), 3) for k, v in db.groupby("pressure").epa.mean().items()},
        "pressure_by_blitz": {str(k): round(float(v), 3) for k, v in db.groupby("blitz").pressure.mean().items()},
        "quick_share": {c: round(float((att[att.covg == c].depth == "quick").mean()), 3) for c in ("C1", "C2")},
        "deep_share": {c: round(float((att[att.covg == c].depth == "deep").mean()), 3) for c in ("C0", "C2")},
    }
    edb = early[early.dropback & early.xpass.notna()]
    bins = pd.cut(edb.xpass, [0, 0.4, 0.7, 1.0], labels=["lo", "mid", "hi"])
    out["dropback_epa_by_xpass"] = {k: round(float(v), 3) for k, v in edb.groupby(bins, observed=True).epa.mean().items()}
    pe = part[(part.dd == "1st") & (part.kind == "run") & part.box.notna() & part.pers.isin(["11", "12", "13"])]
    out["heavy_box_by_pers"] = {k: round(float(v), 3) for k, v in pe.groupby("pers").box.apply(lambda s: (s == "heavy").mean()).items()}
    return out


def sim_effects(plays: list[dict]) -> dict:
    plays = [p for p in plays if not p.get("penalty")]   # 실측 쪽도 반칙 플레이를 뺀다
    early = [p for p in plays if p["down"] in (1, 2)]
    runs = [p for p in early if p["kind"] == "run" and p.get("family") not in ("scramble", None)]
    db = [p for p in plays if p["kind"] == "pass"]
    att = [p for p in db if p.get("depth")]
    out = {
        "run_epa_by_box": {b: m(p["epa"] for p in runs if p.get("box") == b) for b in ("light", "normal", "heavy")},
        "dropback_epa_pressure": {str(k): m(p["epa"] for p in db if p.get("pressure") == k) for k in (0, 1)},
        "pressure_by_blitz": {str(k): m(p.get("pressure", 0) for p in db if p.get("blitz") == k and "pressure" in p)
                              for k in (0, 1)},
        "quick_share": {c: m(p["depth"] == "quick" for p in att if p.get("cov") == c) for c in ("C1", "C2")},
        "deep_share": {c: m(p["depth"] == "deep" for p in att if p.get("cov") == c) for c in ("C0", "C2")},
    }
    edb = [p for p in early if p["kind"] == "pass" and "xp" in p]
    out["dropback_epa_by_xpass"] = {
        "lo": m(p["epa"] for p in edb if p["xp"] < 0.4), "mid": m(p["epa"] for p in edb if 0.4 <= p["xp"] < 0.7),
        "hi": m(p["epa"] for p in edb if p["xp"] >= 0.7)}
    pe = [p for p in plays if p["down"] == 1 and p["togo"] == 10 and p["kind"] == "run" and p.get("pers") in ("11", "12", "13")]
    out["heavy_box_by_pers"] = {k: m(p.get("box") == "heavy" for p in pe if p.get("pers") == k) for k in ("11", "12", "13")}
    return out


def balanced() -> dict:
    from gridiron.tactics.model import Tactics
    return Tactics().to_dict()


def with_run_share(r: float) -> dict:
    from gridiron.tactics.model import Tactics
    t = Tactics()
    t.offense.run_share = r
    return t.to_dict()


# ── 테스트 ────────────────────────────────────────────────────────
def t1_t2(pool, scale, results):
    lg, _ = league()
    teams = sorted(lg.teams)
    specs = []
    games = int(1200 * scale)
    for i in range(8):
        # T1은 리그 재현이므로 각 팀의 실측 성향 전술·숙련도를 그대로 쓴다
        specs.append({"teams": (teams[(2 * i) % 32], teams[(2 * i + 1) % 32]), "seeds": list(range(i, games, 8)),
                      "neutral": False})
    out = merge(run_many(pool, specs))
    sim = sim_effects(out["plays"])
    real = real_effects()
    results["T1"] = {"games": games, "sim": sim, "real": real}
    s_lo, s_hi = sim["dropback_epa_by_xpass"]["lo"], sim["dropback_epa_by_xpass"]["hi"]
    r_lo, r_hi = real["dropback_epa_by_xpass"]["lo"], real["dropback_epa_by_xpass"]["hi"]
    slope_s, slope_r = s_hi - s_lo, r_hi - r_lo
    results["T2"] = {"sim_slope": round(slope_s, 4), "real_slope": round(slope_r, 4),
                     "ratio": round(slope_s / slope_r, 2) if slope_r else None,
                     "pass": slope_r != 0 and 0.7 <= slope_s / slope_r <= 1.3}


def t3(pool, scale, results):
    from gridiron.tactics.model import Tactics, preset
    games = int(600 * scale)
    out = {}
    for style in ("outside_zone", "gap"):
        t = Tactics()
        t.offense.run_style = style
        spec = {"teams": (X, Y), "tac": {X: t.to_dict()}, "mods": {X: ["strong_ol"]}}
        r = merge(run_many(pool, chunks(spec, games, 4, 100)))
        out[style] = m(p["epa"] for p in r["plays"] if p["o"] == X and p["kind"] == "run" and p.get("family") != "scramble")
    run_diff = out["gap"] - out["outside_zone"]
    cov = {}
    for name in ("tampa2", "man_blitz"):
        spec = {"teams": (X, Y), "tac": {Y: preset("balanced", name).to_dict()}, "mods": {Y: ["man_cb"]}}
        r = merge(run_many(pool, chunks(spec, games, 4, 200)))
        cov[name] = m(p["epa"] for p in r["plays"] if p["o"] == X and p["kind"] == "pass")
    pass_diff = cov["tampa2"] - cov["man_blitz"]
    results["T3"] = {"strong_ol_run_epa": out, "run_diff_gap_minus_zone": round(run_diff, 4),
                     "man_cb_pass_epa_allowed": cov, "pass_diff_zone_minus_man": round(pass_diff, 4),
                     "pass": run_diff >= 0.03 and pass_diff >= 0.02}


def t4(pool, scale, results):
    games = int(2400 * scale)   # 전·후반 차이의 차이라 잡음이 커서(표준오차 약 0.01) 표본을 크게 잡는다
    out = {}
    tac = with_run_share(0.1)
    tac["predictability"]["tendency_break"] = "off"   # 뻔한 전술의 대가를 재므로 완화 수단(성향 깨기)은 끈다
    for learning in (True, False):
        spec = {"teams": (X, Y), "tac": {X: tac, Y: balanced()}, "learning": learning}
        r = merge(run_many(pool, chunks(spec, games, 4, 300)))
        # 접전 상황만: 학습으로 효율이 떨어진 팀은 후반에 뒤지는 일이 많고, 뒤진 팀의 패스는 프리벤트 수비 보정으로
        # 좋아지므로(경기 흐름 효과) 전·후반 비교가 가려진다
        mine = [p for p in r["plays"] if p["o"] == X and p.get("gs", "close") == "close"]
        e1 = [p["epa"] for p in mine if p["q"] <= 2]
        e2 = [p["epa"] for p in mine if p["q"] in (3, 4)]
        h1, h2 = m(e1), m(e2)
        out["learning" if learning else "control"] = {
            "first_half": h1, "second_half": h2, "diff": round(h2 - h1, 4),
            "se_diff": round(math.sqrt(se(e1) ** 2 + se(e2) ** 2), 4), "pass_rate": m(p["kind"] == "pass" for p in mine)}
    excess = out["learning"]["diff"] - out["control"]["diff"]
    # 설계 기준: 학습 시 후반 − 전반 ≤ −0.02, 대조군은 차이 없음 (표준오차 2배 이내)
    ctl = out["control"]
    results["T4"] = {**out, "excess_drop": round(excess, 4),
                     "pass": out["learning"]["diff"] <= -0.02 and abs(ctl["diff"]) <= 2 * ctl["se_diff"]}


def t5(pool, scale, results):
    """런 비율 곡선. 점마다 잡음(±0.01)이 커서 2차 곡선을 맞춘 정점을 최적 런 비율로 본다."""
    import numpy as np
    games = int(800 * scale)
    shares = [0.15, 0.25, 0.35, 0.45, 0.55, 0.7]
    curves, best = {}, {}
    for label, mods in (("average", []), ("elite_run_weak_qb", ["elite_run"])):
        curve = {}
        for r_ in shares:
            spec = {"teams": (X, Y), "tac": {X: with_run_share(r_), Y: balanced()}, "mods": {X: mods}}
            r = merge(run_many(pool, chunks(spec, games, 4, 400)))
            curve[r_] = m(p["epa"] for p in r["plays"] if p["o"] == X)
        curves[label] = curve
        a, b, _ = np.polyfit(shares, [curve[s] for s in shares], 2)
        peak = -b / (2 * a) if a < 0 else (shares[-1] if b > 0 else shares[0])
        best[label] = round(float(min(max(peak, shares[0]), shares[-1])), 3)
    results["T5"] = {"curves": {k: {str(a): b for a, b in v.items()} for k, v in curves.items()}, "best": best,
                     "pass": 0.25 <= best["average"] <= 0.45 and best["elite_run_weak_qb"] > best["average"]}


def t6(pool, scale, results):
    from gridiron.tactics.model import preset
    offs, defs = ("west_coast", "air_raid", "ground_pound", "wide_zone"), ("tampa2", "man_blitz", "quarters")
    combos = [f"{o}+{d}" for o in offs for d in defs]
    games = max(8, int(40 * scale))
    specs, keys = [], []
    for i, a in enumerate(combos):
        for b in combos[i + 1:]:
            ta, tb = preset(*a.split("+")).to_dict(), preset(*b.split("+")).to_dict()
            # 같은 두 로스터에 전술을 바꿔 걸어 로스터 차이를 상쇄
            specs.append({"teams": (X, Y), "tac": {X: ta, Y: tb}, "seeds": list(range(500, 500 + games // 2)),
                          "pbp": False})
            specs.append({"teams": (X, Y), "tac": {X: tb, Y: ta}, "seeds": list(range(900, 900 + games // 2)),
                          "pbp": False})
            keys += [(a, b, X), (b, a, X)]
    outs = run_many(pool, specs)
    wins = defaultdict(float)
    games_n = defaultdict(int)
    h2h = {}
    for (a, b, x), o in zip(keys, outs):
        for res in o["results"]:
            pa, pb = res[x], res[Y]
            w = 1.0 if pa > pb else 0.5 if pa == pb else 0.0
            wins[a] += w
            wins[b] += 1 - w
            games_n[a] += 1
            games_n[b] += 1
            h2h.setdefault(tuple(sorted((a, b))), []).append(w if a < b else 1 - w)
    rate = {k: round(wins[k] / games_n[k], 3) for k in combos}
    strong = {f"{a} vs {b}": round(mean(v), 3) for (a, b), v in h2h.items() if abs(mean(v) - 0.5) >= 0.15}
    results["T6"] = {"win_rate": rate, "max": max(rate.values()), "lopsided_pairs": strong,
                     "pass": max(rate.values()) <= 0.60 and len(strong) > 0}


def t7(pool, scale, results):
    """존 위주 팀(맨 커버리지 55, 블리츠 60)이 맨 블리츠로 전환. 숙련도는 실제 주간 규칙으로 올린다:
    훈련 자동 초점(가장 낮은 사용 영역 +5, 나머지 +1.5) + 경기 사용(비중 20% 이상 +2)."""
    from gridiron.tactics import familiarity as F
    from gridiron.tactics.model import preset
    from gridiron.tactics.training import TrainingPlan, apply_week
    games = int(800 * scale)
    fam = {**F.default(), "cov_man": 55.0, "blitz": 60.0}
    usage = {"cov_man": 60, "cov_zone": 40, "def_pass_total": 100, "blitz": 45}
    weeks = []
    for wk in range(6):
        weeks.append({"cov_man": round(fam["cov_man"], 1), "blitz": round(fam["blitz"], 1)})
        fam, _, _ = apply_week(TrainingPlan(main="familiarity:auto", sub=None), fam, ["cov_man", "blitz"])
        fam = F.after_game(fam, usage)
    out = {}
    for wk, f in enumerate(weeks + [{"cov_man": 80.0, "blitz": 80.0}]):
        spec = {"teams": (X, Y), "tac": {Y: preset("balanced", "man_blitz").to_dict()}, "fam": {Y: f}}
        r = merge(run_many(pool, chunks(spec, games, 4, 600)))
        out[wk if wk < len(weeks) else "baseline"] = m(p["epa"] for p in r["plays"] if p["o"] == X and p["kind"] == "pass")
    base = out["baseline"]
    d0, d3 = out[0] - base, out[3] - base
    results["T7"] = {"familiarity_by_week": weeks, "pass_epa_allowed_by_week": out, "deficit_week0": round(d0, 4),
                     "deficit_week3": round(d3, 4), "pass": d0 >= 0.02 and d3 <= 0.5 * d0}


def t8(pool, scale, results):
    spec = {"teams": (X, Y), "explain": True}
    r = merge(run_many(pool, chunks(spec, max(8, int(40 * scale)), 4, 700)))
    worst, n = 0.0, 0
    for p in r["plays"]:
        if "s_total" in p:
            s = p["s_rating"] + p["s_fam"] + p["s_anticip"] + p["s_drill"] + p["s_home"] + p.get("s_situ", 0.0)
            worst = max(worst, abs(s - p["s_total"]))
            n += 1
    results["T8"] = {"plays_checked": n, "max_abs_error": round(worst, 6), "pass": n > 0 and worst < 2e-3}


def t9(pool, scale, results):
    """켬·끔을 번갈아 5회씩 재고 각각 최솟값을 비교한다 (다른 프로세스 부하에 따른 잡음 제거)."""
    games = int(100 * scale)
    times = {"off": [], "on": []}
    for _ in range(5):
        for learning in (False, True):
            r = run_job({"teams": (X, Y), "seeds": list(range(800, 800 + games)), "learning": learning, "pbp": False})
            times["on" if learning else "off"].append(r["secs"] / games)
    out = {k: round(min(v), 4) for k, v in times.items()}
    inc = out["on"] / out["off"] - 1
    results["T9"] = {"sec_per_game": out, "increase": round(inc, 3), "pass": inc <= 0.10}


TESTS = {"t1": t1_t2, "t3": t3, "t4": t4, "t5": t5, "t6": t6, "t7": t7, "t8": t8, "t9": t9}


def main() -> None:
    global X, Y
    ap = argparse.ArgumentParser()
    ap.add_argument("tests", nargs="*", default=["all"])
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    X, Y = pair()
    names = list(TESTS) if args.tests == ["all"] else [t if t != "t2" else "t1" for t in args.tests]
    results: dict = {"teams": [X, Y]}
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(X, Y)) as pool:
        for name in dict.fromkeys(names):
            t0 = time.time()
            TESTS[name](pool, args.scale, results)
            print(f"{name}: {time.time() - t0:.0f}s")
    for k, v in results.items():
        if k != "teams":
            print(k, json.dumps(v, ensure_ascii=False))
    if args.out:
        old = json.loads(args.out.read_text()) if args.out.exists() else {}
        old.update(results)
        args.out.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")


def _init(x, y):
    global X, Y
    X, Y = x, y


if __name__ == "__main__":
    main()
