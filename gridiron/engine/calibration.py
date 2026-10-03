"""엔진 보정 측정 (ENGINE_DESIGN §5.5).

평균 매치업 중심값(center): 리그 경기를 돌려 결과 모델의 능력치 차이 Δ 평균을 잰다. 실측 기준 분포에는
"주전이 더 자주 뛰고 타깃은 좋은 리시버에게 몰린다"는 평균 선택 효과가 이미 들어 있으므로, 평균적인 매치업에서
Δ가 0이 되도록 이 값을 빼 준다. 능력치 분포가 바뀌면(샘플 리그 ↔ 실측 능력치) 다시 잰다.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

from ..domain.models import League
from .adapter import build_team
from .norms import compute_norms
from .outcome.data_model import DataOutcome
from .skeleton.game import GameSim
from .skeleton.settings import GameSettings

KEYS = {"d_rush": "rush", "d_pass": "pass", "d_int": "int", "d_yac": "yac", "pocket": "pocket",
        "mobility": "mobility", "d_run": "run", "d_scr": "scramble"}


def measure_centers(league: League, n_games: int = 300, seed: int = 0) -> dict[str, float]:
    norms = compute_norms(league)
    games = [g for g in league.schedule if g.game_type == "REG"]
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

    for i in range(n_games):
        gm = games[i % len(games)]
        GameSim([build_team(league, gm.home, 0, gm.gameday), build_team(league, gm.away, 1, gm.gameday)],
                settings=GameSettings.from_config(), outcome=Probe(center={}), seed=seed + i, norms=norms).run()
    return {name: round(mean(vals[k]), 3) for k, name in KEYS.items() if vals[k]}
