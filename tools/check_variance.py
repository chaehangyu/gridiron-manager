"""경기 결과 변동성 점검 (M7c): 같은 매치업을 반복해 '실력으로 설명되지 않는' 점수 차 잡음을 잰다.

실측 기준 (NFL 2015–2024): 팀 경기당 득점 SD ≈ 10, 경기 득실차 SD ≈ 14.5, 예상 득실차(라스베이거스 라인) 대비 잔차 SD ≈ 13.4,
경기당 턴오버 ≈ 1.3/팀, 20야드+ 플레이 ≈ 3.5/팀.

    python tools/check_variance.py [매치업 수=24] [반복=12]
"""
from __future__ import annotations

import statistics
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gridiron.data.real_league import load_real_league  # noqa: E402
from gridiron.engine.api import simulate  # noqa: E402


def run(n_match: int = 24, reps: int = 12) -> dict:
    lg = load_real_league(2026)
    games = lg.schedule[::max(1, len(lg.schedule) // n_match)][:n_match]
    resid, margins, pts, tos = [], [], [], []
    for g in games:
        ms = []
        for r in range(reps):
            out = simulate(lg, g, seed=zlib.crc32(f"var:{g.game_id}:{r}".encode()), play_by_play=False, injuries=False)
            m = out.home_score - out.away_score
            ms.append(m)
            pts += [out.home_score, out.away_score]
            for t in out.box["teams"].values():
                tos.append(t.get("pssInt", 0) + t.get("fmbLost", 0))
        mu = statistics.mean(ms)
        resid += [m - mu for m in ms]
        margins += ms
    k = reps / (reps - 1)       # 표본 평균을 빼서 줄어든 분산 보정
    out = {"resid_sd": round((statistics.pvariance(resid) * k) ** 0.5, 2), "margin_sd": round(statistics.pstdev(margins), 2),
           "pts_sd": round(statistics.pstdev(pts), 2), "pts_mean": round(statistics.mean(pts), 2),
           "to_per_team": round(statistics.mean(tos), 2)}
    for k_, v in out.items():
        print(f"{k_:<12} {v}")
    return out


if __name__ == "__main__":
    run(*(int(a) for a in sys.argv[1:3]))
