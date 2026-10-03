"""상황별 결과 보정값 적합 (M4 구현 노트, ENGINE_DESIGN §15).

M2 기준 분포는 결과를 깊이·압박·커버리지·박스 등으로 나누지만, 다운·거리와 점수·시간 상황에 따른 차이
(퍼스트다운 선을 의식한 수비·QB 판단, 크게 앞선 팀의 프리벤트 수비 등)는 일부만 들어 있다.
같은 EP 모델로 계산한 실측 EPA와 시뮬 EPA를 상황별로 맞추는 이동값을 반복 적합한다.
- pass: 다운·거리 구간 (에어·YAC 분위수에 더함 — 완성률은 이미 실측과 맞아 건드리지 않는다)
- pass_gs: 점수·시간 상황 (close는 0으로 고정)
- pass_fz: 필드 구역 (opp는 0으로 고정; 레드존 터치다운률 등)
- run: 다운·거리 구간 (런 야드 분위수)

사용법: python tools/calibrate_situations.py [반복=3] [경기 수=1600]  → config/engine.yaml의 situation_shift
"""
import json
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import validate_tactics as V  # noqa: E402

from gridiron.baseline.build import PART_SEASONS, load  # noqa: E402
from gridiron.config import DATA_DIR, load as load_cfg  # noqa: E402

ITER = int(sys.argv[1]) if len(sys.argv) > 1 else 3
GAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 1600
SLOPE = {"pass": 0.45, "pass_gs": 0.45, "pass_fz": 0.45, "run": 0.9}
# 보정하는 축. 패스 다운·거리(pass)와 자기 진영은 맞추면 패스 야드/시도가 7.5 이상으로 부풀어(같은 야드를
# 득점으로 덜 바꾸는 기준 분포의 한계) 빼고, 레드존·골라인(터치다운률)과 점수·시간 상황만 맞춘다.
GROUPS = ("pass_gs", "pass_fz", "run")   # 이동 1당 EPA 변화 (반복 적합에서 측정한 근사값)


def real_targets() -> dict:
    d = load(DATA_DIR / "raw")
    d = d[(d.season_type == "REG") & d.season.isin(PART_SEASONS)].drop(columns=["epa"]).merge(
        V.ours_epa(PART_SEASONS), on=["game_id", "play_id"])
    d = d[d.epa.notna() & (d.penalty != 1)]
    db = d[d.dropback]
    runs = d[(d.kind == "run") & (d.qb_scramble != 1)]
    agg = lambda s, key: {k: (float(g.epa.mean()), len(g)) for k, g in s.groupby(key)}  # noqa: E731
    from gridiron.engine.ai.coordinator import field5
    db = db.assign(fz=db.yardline_100.map(field5))
    return {"pass": agg(db, "dd"), "pass_gs": agg(db, "gs"), "pass_fz": agg(db, "fz"), "run": agg(runs, "dd")}


def sim_targets(shift: dict) -> dict:
    lg, _ = V.league()
    teams = sorted(lg.teams)
    specs = [{"teams": (teams[2 * i], teams[2 * i + 1]), "seeds": list(range(i, GAMES, 8)), "situ": shift,
              "neutral": False} for i in range(8)]
    with ProcessPoolExecutor(4) as ex:
        plays = [p for o in ex.map(V.run_job, specs) for p in o["plays"]]
    from gridiron.engine.ai.coordinator import field5
    out = {"pass": {}, "pass_gs": {}, "pass_fz": {}, "run": {}}
    for p in plays:
        if "dd" not in p or p.get("penalty"):   # 실측 쪽과 같이 반칙 플레이는 뺀다
            continue
        if p["kind"] == "pass":
            out["pass"].setdefault(p["dd"], []).append(p["epa"])
            out["pass_gs"].setdefault(p.get("gs", "close"), []).append(p["epa"])
            out["pass_fz"].setdefault(field5(p["yl"]), []).append(p["epa"])
        elif p.get("family") not in ("scramble", None):
            out["run"].setdefault(p["dd"], []).append(p["epa"])
    return {g: {k: (st.mean(v), len(v)) for k, v in d.items()} for g, d in out.items()}


def main() -> None:
    real = real_targets()
    cur = load_cfg("engine").get("situation_shift") or {}
    shift = {g: dict(cur.get(g, {})) for g in ("pass", "pass_gs", "pass_fz", "run")}
    for it in range(ITER):
        sim = sim_targets(shift)
        print(f"반복 {it + 1}")
        for group in ("pass", "pass_gs", "pass_fz", "run"):
            for k in sorted(real[group]):
                if k not in sim[group] or k.startswith("4") or k in ("close", "opp"):
                    continue
                if group not in GROUPS or (group == "pass_fz" and k not in ("red", "goal")):
                    continue   # 4th down은 표본이 작고 분산이 커서, close는 기준(0)이라 보정하지 않는다
                (r, rn), (s, sn) = real[group][k], sim[group][k]
                w = min(1.0, sn / 2000)
                shift[group][k] = round(shift[group].get(k, 0.0) + 0.45 * w * (r - s) / SLOPE[group], 3)
                print(f"  {group:7s} {k:7s} 실측 {r:+.3f} ({rn})  시뮬 {s:+.3f} ({sn})  → 이동 {shift[group][k]:+.3f}")
    print(json.dumps(shift, ensure_ascii=False))


if __name__ == "__main__":
    main()
