"""시즌 구조 (PRD F1-4·F1-5·F1-6, M5): 공식 타이브레이커·시드·플레이오프 진행."""
import csv
import json
from pathlib import Path

import pytest

from gridiron.data.sample import generate_sample_league
from gridiron.domain.models import ScheduledGame
from gridiron.season import standings as ST

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def real_teams():
    from gridiron.data.real_league import load_real_league
    return load_real_league(2026)


@pytest.mark.parametrize("season", [2021, 2022, 2023, 2024, 2025])
def test_wildcard_matchups_match_real_nfl(real_teams, season):
    """실제 정규시즌 결과로 계산한 시드 → 와일드카드 대진이 실제와 같다 (2021–2025 전부)."""
    lg = real_teams
    lg.season = season
    with open(FIX / "nfl_results_2021_2025.csv", encoding="utf-8") as fh:
        lg.schedule = [ScheduledGame(f"{season}_{i}", season, int(r["week"]), "REG", r["home"], r["away"],
                                     home_score=int(r["home_score"]), away_score=int(r["away_score"]))
                       for i, r in enumerate(csv.DictReader(fh)) if int(r["season"]) == season]
    st = ST.compute(lg)
    mine = sorted([st.seeds[c][a], st.seeds[c][b]] for c in ("AFC", "NFC") for a, b in ((1, 6), (2, 5), (3, 4)))
    real = json.loads((FIX / "nfl_wildcard_2021_2025.json").read_text())[str(season)]
    assert mine == sorted(real)


def _finish(lg, score):
    for g in lg.schedule:
        if not g.played:
            g.home_score, g.away_score = score(g)


def test_playoff_bracket_flow():
    lg = generate_sample_league(season=2026)
    _finish(lg, lambda g: (24, 17) if g.home < g.away else (10, 20))
    rounds = []
    while True:
        new = ST.next_round(lg)
        if not new:
            break
        rounds.append((new[0].game_type, len(new), new[0].week))
        lg.schedule.extend(new)
        _finish(lg, lambda g: (27, 20))       # 홈(상위 시드) 승
    w = ST.reg_weeks(lg)
    assert rounds == [("WC", 6, w + 1), ("DIV", 4, w + 2), ("CON", 2, w + 3), ("SB", 1, w + 4)]
    st = ST.compute(lg)
    div = [g for g in lg.schedule if g.game_type == "DIV"]
    for conf in ("AFC", "NFC"):
        s = st.seeds[conf]
        # 상위 시드가 모두 이기면 1–4번 시드가 디비저널에 남고 1번은 4번과 만난다
        assert any(g.home == s[0] and g.away == s[3] for g in div)
    sb = next(g for g in lg.schedule if g.game_type == "SB")
    assert sb.neutral_site and ST.champion(lg) == sb.home
    assert sb.home == st.seeds["AFC"][0]          # 2026 시즌 = 슈퍼볼 61회(홀수) → AFC 홈 표기
    order = ST.draft_order(lg)
    assert order[-1] == ST.champion(lg) and order[-2] == sb.away
    assert set(order[:18]).isdisjoint({t for s in st.seeds.values() for t in s})


def test_division_h2h_and_coin_are_deterministic():
    lg = generate_sample_league(season=2026)
    _finish(lg, lambda g: (20, 20))      # 전 경기 무승부 → 끝까지 동률이면 동전(결정론)
    a = ST.compute(lg)
    b = ST.compute(lg)
    assert a.seeds == b.seeds and len(a.seeds["AFC"]) == 7


def test_season_runner_end_to_end(tmp_path):
    """세이브 위에서 정규시즌 → 플레이오프 → 시즌 종료까지 (샘플 리그, 경기 결과는 빠른 가짜 시뮬)."""
    from gridiron.db.store import load_league, save_league
    from gridiron.season import runner

    lg = generate_sample_league(season=2026)
    path = tmp_path / "s.sqlite"
    save_league(lg, path, user_team=next(iter(lg.teams)))
    league, user = load_league(path)
    # 정규시즌은 직접 결과를 채워 저장 (엔진 시간 절약), 플레이오프는 실제 엔진으로
    from gridiron.db.store import record_game
    for g in league.schedule:
        g.home_score, g.away_score = (21, 14) if g.home < g.away else (13, 17)
        record_game(path, g, {"overtimes": 0}, 0, {"teams": {}, "players": {}})
    league.week = ST.reg_weeks(league)
    notes = runner.finish_week(path, league, league.week)
    assert league.phase == "playoffs" and any("시드" in n for n in notes)
    while not runner.season_over(league):
        runner.sim_week(path, league, None)     # 구단주 계산(엔진 1분)은 test_owner에서
    again, _ = load_league(path)
    assert again.phase == "offseason" and ST.champion(again) == ST.champion(league)
    assert sum(g.game_type != "REG" for g in again.schedule) == 13
