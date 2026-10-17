"""부상 지표 점검 (PRD M5 완료 기준 "부상 지표 통과"): 실제 리그로 정규시즌을 돌려 실측(data/baseline/injuries.json)과 비교.

    python tools/check_injuries.py [시즌 수=1]
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gridiron.data.real_league import load_real_league  # noqa: E402
from gridiron.engine.api import simulate  # noqa: E402
from gridiron.engine.injury import data  # noqa: E402
from gridiron.season import injuries as INJ  # noqa: E402
from gridiron.season.weekly import after_game, prepare_week  # noqa: E402


def run(n_seasons: int = 1) -> dict:
    events, team_games, ir_end = [], 0, []
    for k in range(n_seasons):
        lg = load_real_league(2026)
        for week in range(1, 19):
            prepare_week(lg, week)
            games = lg.games_in_week(week)
            for g in games:
                out = simulate(lg, g, seed=k * 1000 + hash(g.game_id) % 1000, play_by_play=False)
                after_game(lg, out.tactics, out.box["players"])
                INJ.apply_game(lg, g, out.injuries)
                team_games += 2
                events += [(x["missed"] if not x["season_out"] else 99, x["part"], x.get("returned", False))
                           for x in out.injuries]
            INJ.after_week(lg, week, {t for g in games for t in (g.home, g.away)})
            INJ.auto_ir(lg, week, set(lg.teams))
            lg.week = week + 1
        ir_end.append(sum(1 for p in lg.players.values() if p.roster_status.value == "ir" and p.ir_week) / 32)
    long = data()["long"]
    m = [e[0] for e in events]
    n = len(m)
    res = {"per_team_game": round(n / team_games, 3),
           "zero": round(sum(x == 0 for x in m) / n, 3), "one_three": round(sum(1 <= x <= 3 for x in m) / n, 3),
           "four_seven": round(sum(4 <= x < long for x in m) / n, 3), "long": round(sum(x >= long for x in m) / n, 3),
           "in_game_return": round(sum(e[2] for e in events) / n, 3),
           "season_ir_per_team": round(sum(ir_end) / len(ir_end), 2),
           "parts": dict(Counter(e[1] for e in events).most_common(6))}
    real = data()
    real_total = real["per_team_game"] + real["silent_season_ending_per_team_game"] * 0.6
    print(f"부상/팀경기   시뮬 {res['per_team_game']:.2f}   실측 {real_total:.2f} (리포트 {real['per_team_game']:.2f} + 리포트 밖 중상)")
    mo = real["missed_overall"]
    for k in ("zero", "one_three", "four_seven", "long"):
        print(f"결장 {k:<10} 시뮬 {res[k]:.3f}   실측 {mo[k]:.3f}")
    print(f"경기 중 복귀 {res['in_game_return']:.3f} · 시즌 중 IR 등재(팀당) {res['season_ir_per_team']} · 부위 {res['parts']}")
    return res


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
