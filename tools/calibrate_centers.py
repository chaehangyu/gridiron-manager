"""평균 매치업 중심 보정값 측정 (ENGINE_DESIGN §5.5).

샘플 리그 경기를 돌려 결과 모델의 능력치 차이 Δ 평균을 잰다. 평균적인 매치업에서 Δ가 0이 되도록
config/engine.yaml의 center 값으로 쓴다 (실측 기준 분포에 이미 평균 선택 효과가 들어 있기 때문).

사용법: python tools/calibrate_centers.py [경기 수=200]
"""
import sys
from collections import defaultdict
from statistics import mean

from gridiron.data.sample import generate_sample_league
from gridiron.engine.adapter import build_team
from gridiron.engine.norms import compute_norms
from gridiron.engine.outcome.data_model import DataOutcome
from gridiron.engine.skeleton.game import GameSim
from gridiron.engine.skeleton.settings import GameSettings

N_GAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 200
KEYS = {"d_rush": "rush", "d_pass": "pass", "d_int": "int", "d_yac": "yac", "pocket": "pocket",
        "mobility": "mobility", "d_run": "run", "d_scr": "scramble"}

league = generate_sample_league()
norms = compute_norms(league)
vals: dict[str, list[float]] = defaultdict(list)


class Probe(DataOutcome):
    def pass_play(self, g):
        plan = super().pass_play(g)
        for k in KEYS:
            if k in plan.extra:
                vals[k].append(plan.extra[k])
        return plan

    def run_play(self, g, positions, scramble):
        plan = super().run_play(g, positions, scramble)
        for k in KEYS:
            if k in plan.extra:
                vals[k].append(plan.extra[k])
        return plan


for i in range(N_GAMES):
    gm = league.schedule[i % len(league.schedule)]
    GameSim([build_team(league, gm.home, 0, gm.gameday), build_team(league, gm.away, 1, gm.gameday)],
            settings=GameSettings.from_config(), outcome=Probe(), seed=i, norms=norms).run()

current = DataOutcome().center
print("현재 center에 더할 값 (평균 Δ):")
for k, name in KEYS.items():
    if vals[k]:
        print(f"  {name}: {current.get(name, 0.0) + mean(vals[k]):+.3f}   (측정 평균 {mean(vals[k]):+.3f}, n={len(vals[k])})")
