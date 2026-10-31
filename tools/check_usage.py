"""선수 사용량 분포 점검 (M7c): 실제 리그 정규시즌을 엔진으로 돌려 팀별 타깃·캐리 점유율과 시즌 리더 기록을 본다.

실측 기준(2021–2025 NFL 정규시즌 대략값):
- 팀 1번 타깃 점유율 평균 ≈ 0.26 (최고 ≈ 0.32), 2번 ≈ 0.19
- 팀 1번 RB 캐리 점유율(팀 전체 러싱 시도 대비) 평균 ≈ 0.55 (최고 ≈ 0.75)
- 시즌 리더: 리시빙 ≈ 1,700–1,950야드 · 리셉션 ≈ 120–145, 러싱 ≈ 1,700–2,000야드, 색 ≈ 17–22, 태클 ≈ 150–175

    python tools/check_usage.py [시즌 수=1]
"""
from __future__ import annotations

import statistics
import sys
import zlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gridiron.data.real_league import load_real_league  # noqa: E402
from gridiron.engine.api import simulate  # noqa: E402
from gridiron.season.game_report import derive  # noqa: E402


def run(n: int = 1) -> dict:
    res = defaultdict(list)
    for k in range(n):
        lg = load_real_league(2026)
        tot = defaultdict(lambda: defaultdict(float))
        team_of = {}
        for g in lg.schedule:
            out = simulate(lg, g, seed=zlib.crc32(f"use{k}:{g.game_id}".encode()), play_by_play=False, injuries=False)
            for pid, (t, s) in out.box["players"].items():
                team_of[pid] = t
                for key, v in derive(s).items():
                    if isinstance(v, (int, float)):
                        tot[pid][key] += v
        by_team = defaultdict(list)
        for pid, s in tot.items():
            by_team[team_of[pid]].append((pid, s))
        for t, rows in by_team.items():
            tg = sorted((s.get("tgt", 0) for _, s in rows), reverse=True)
            ru = sorted(((s.get("rus", 0), lg.players[pid].position.value) for pid, s in rows), reverse=True)
            ttg, trus = sum(tg), sum(r for r, _ in ru)
            res["tgt1"].append(tg[0] / ttg)
            res["tgt2"].append(tg[1] / ttg)
            rb = [r for r, pos in ru if pos == "RB"]
            res["rb1"].append(rb[0] / trus if rb else 0)
        for key in ("recYds", "rec", "rusYds", "defSk", "defTck", "pssYds"):
            vals = sorted((s.get(key, 0) for s in tot.values()), reverse=True)
            res["top_" + key].append(vals[0])
            res["10th_" + key].append(vals[9])
    out = {k: round(statistics.mean(v), 3) for k, v in res.items()}
    out["tgt1_max"] = round(max(res["tgt1"]), 3)
    out["rb1_max"] = round(max(res["rb1"]), 3)
    for k, v in out.items():
        print(f"{k:<14} {v}")
    return out


def override(pairs: list[str]) -> None:
    """usage.<키>=값 덮어쓰기 (탐색용): python tools/check_usage.py 1 target_skill=0.35 rb2_share=0.3"""
    from gridiron.engine.outcome import data_model as DM
    base = DM._params()
    usage = dict(base.get("usage", {}))
    for kv in pairs:
        k, v = kv.split("=")
        usage[k] = float(v)
    patched = {**base, "usage": usage}
    DM._params = lambda: patched


if __name__ == "__main__":
    override(sys.argv[2:])
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
