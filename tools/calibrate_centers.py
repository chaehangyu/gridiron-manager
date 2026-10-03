"""평균 매치업 중심 보정값 측정 (ENGINE_DESIGN §5.5) — gridiron.engine.calibration.measure_centers 실행기.

출력값을 config/engine.yaml에 그대로 쓴다: 실제 리그는 `center`, 샘플 리그는 `center_sample`.

사용법: python tools/calibrate_centers.py [경기 수=300] [리그=real:2026 | sample]
"""
import sys

from gridiron.data.real_league import load_real_league
from gridiron.data.sample import generate_sample_league
from gridiron.engine.calibration import measure_centers

N_GAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 300
SOURCE = sys.argv[2] if len(sys.argv) > 2 else "real:2026"

league = generate_sample_league() if SOURCE == "sample" else load_real_league(int(SOURCE.split(":")[1]))
print(f"{SOURCE} {N_GAMES}경기 — center로 쓸 값 (평균 Δ):")
for name, v in measure_centers(league, N_GAMES).items():
    print(f"  {name}: {v:.3f}")
