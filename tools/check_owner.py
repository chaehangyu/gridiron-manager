"""구단주 기대치 점검 (PRD M5 완료 기준 "구단주 기대치가 실제 성적 분포와 일치").

파워 레이팅(엔진 2회) → 200회 투영을 만든 뒤, 같은 리그로 실제 엔진 시즌을 N번 돌려 비교한다.
- 예상 승수 vs 실제 승수: 상관, 평균 절대 오차, 실제 승수가 예상 ±1SD 안에 든 비율(정규면 약 68%)
- 경기 단위 예상 승률 보정: 구간별 예상 vs 실제 홈 승률, Brier
- 등급별 주 목표 달성률

    python tools/check_owner.py [엔진 시즌 수=3]
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from gridiron.data.real_league import load_real_league  # noqa: E402
from gridiron.domain.models import ScheduledGame  # noqa: E402
from gridiron.engine.api import simulate  # noqa: E402
from gridiron.season import owner as O  # noqa: E402
from gridiron.season import standings as ST  # noqa: E402


def main(n: int = 3) -> None:
    lg = load_real_league(2026)
    power = O.power_ratings(lg, reps=2, seed=2026)
    proj = O.project(lg, power, n=200, seed=2026)
    print(f"파워 레이팅: 홈 이점 {power['hfa']:+.2f}, 잔차 SD {power['sd']:.2f}")
    pred, act, inside, probs, outs = [], [], 0, [], []
    goal_hit = {k: [] for k in O.TIERS}
    for k in range(n):
        lg2 = load_real_league(2026)
        for g in [g for g in lg2.schedule if g.game_type == "REG"]:
            out = simulate(lg2, g, seed=zlib.crc32(f"chk{k}:{g.game_id}".encode()), play_by_play=False, injuries=False)
            probs.append(O.win_prob(power, g.home, g.away, g.neutral_site))
            outs.append(1.0 if out.home_score > out.away_score else 0.5 if out.home_score == out.away_score else 0.0)
        st = ST.compute(lg2)
        po = {t for s in st.seeds.values() for t in s}
        for t, pr in proj.items():
            w = st.rec(t).w + 0.5 * st.rec(t).t
            pred.append(pr["wins_mean"])
            act.append(w)
            inside += abs(w - pr["wins_mean"]) <= pr["wins_sd"]
            tier = O.tier_of(pr)
            main = O.main_goal(pr)
            if main in ("conf_final", "div_round"):
                continue                      # 플레이오프 경기를 돌리지 않으므로 이 검사에서는 뺀다
            goal_hit[tier].append(O.achieved(main, t, st.rec(t), {}, t in po))
    pred, act = np.array(pred), np.array(act)
    print(f"예상 vs 실제 승수: 상관 {np.corrcoef(pred, act)[0, 1]:.2f}, MAE {np.abs(pred - act).mean():.2f}, "
          f"±1SD 안 {inside / len(pred):.2f} (기대 ≈0.68), 실제 SD {act.std():.2f}")
    probs, outs = np.array(probs), np.array(outs)
    print(f"경기 예상 승률 Brier {np.mean((probs - outs) ** 2):.3f} (동전 0.250)")
    for lo, hi in ((0, .3), (.3, .45), (.45, .55), (.55, .7), (.7, 1.01)):
        m = (probs >= lo) & (probs < hi)
        if m.any():
            print(f"  예상 {lo:.2f}–{hi:.2f}: 평균 {probs[m].mean():.3f} → 실제 {outs[m].mean():.3f} ({m.sum()}경기)")
    for tier, hits in goal_hit.items():
        if hits:
            print(f"주 목표 달성률 {O.TIERS[tier]}: {np.mean(hits):.2f} ({len(hits)}팀-시즌)")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
