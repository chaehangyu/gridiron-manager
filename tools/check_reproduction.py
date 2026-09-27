"""실측 조건부 구조 재현 점검 (ENGINE_DESIGN §11 T1 일부).

샘플 리그 경기를 돌려, 시뮬레이션의 조건별 비율이 실측 표와 같은 모양인지 비교한다.
사용법: python tools/check_reproduction.py [경기 수=300]
"""
import sys
from collections import Counter, defaultdict
from statistics import mean

from gridiron.baseline.tables import lookup, tables
from gridiron.data.sample import generate_sample_league
from gridiron.engine.adapter import build_team
from gridiron.engine.norms import compute_norms
from gridiron.engine.outcome.data_model import DataOutcome
from gridiron.engine.skeleton.game import GameSim
from gridiron.engine.skeleton.settings import GameSettings

N_GAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 300
league = generate_sample_league()
norms = compute_norms(league)
drop = []   # (blitz, pressure, cov, depth, complete, throwaway)
runs = []   # (box, yds)


class Probe(DataOutcome):
    def pass_play(self, g):
        plan = super().pass_play(g)
        e = plan.extra
        if "pressure" in e:
            drop.append((e["blitz"], e["pressure"], e["cov"], e.get("depth"), plan.complete, e.get("throwaway", False),
                         plan.sack))
        return plan

    def run_play(self, g, positions, scramble):
        plan = super().run_play(g, positions, scramble)
        if not scramble:
            runs.append((plan.extra.get("box"), plan.yds))
        return plan


for i in range(N_GAMES):
    gm = league.schedule[i % len(league.schedule)]
    GameSim([build_team(league, gm.home, 0, gm.gameday), build_team(league, gm.away, 1, gm.gameday)],
            settings=GameSettings.from_config(), outcome=Probe(), seed=i, norms=norms).run()

print(f"드롭백 {len(drop)}, 런 {len(runs)}")
print("\n압박률 × 블리츠 (실측 E4: 블리츠 없음 25.6%, 블리츠 39.4%)")
for b in (0, 1):
    xs = [d for d in drop if d[0] == b]
    print(f"  블리츠 {b}: {mean(x[1] for x in xs) * 100:.1f}%  (n={len(xs)})")

print("\n커버리지별 실제 던진 깊이 비율 (시뮬 / 실측 비율 기준)")
thrown = [d for d in drop if d[3] and not d[6]]
base = Counter(d[3] for d in thrown)
tot = sum(base.values())
for cov in ("C0", "C1", "2M", "C2", "C3", "QTR"):
    xs = [d for d in thrown if d[2] == cov]
    c = Counter(d[3] for d in xs)
    sim = {k: (c[k] / len(xs)) / (base[k] / tot) for k in ("screen", "quick", "inter", "deep")} if xs else {}
    real = tables()["depth_ratio_cov"][cov]
    print(f"  {cov:4} " + "  ".join(f"{k} {sim.get(k, 0):.2f}/{real[k]:.2f}" for k in ("screen", "quick", "inter", "deep")))

print("\n완성률 × 깊이 × 압박 (스로어웨이 제외, 시뮬 / 실측)")
for depth in ("screen", "quick", "inter", "deep"):
    for pr in (0, 1):
        xs = [d for d in thrown if d[3] == depth and d[1] == pr and not d[5]]
        real = lookup("pass_rates", depth, pr, "*", "*", "*")["cmp"]
        if xs:
            print(f"  {depth:6} 압박{pr}: {mean(x[4] for x in xs) * 100:.1f}% / {real * 100:.1f}%  (n={len(xs)})")

print("\n런 평균 야드 × 박스 (시뮬)")
for box in ("light", "normal", "heavy"):
    ys = [y for b, y in runs if b == box]
    if ys:
        print(f"  {box:6}: {mean(ys):.2f}야드  (n={len(ys)}, 비율 {len(ys) / len(runs) * 100:.0f}%)")
