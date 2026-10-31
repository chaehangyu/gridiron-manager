"""구단주 목표·신뢰도·평가 (PRD F12, M5d). 엔진 파워 레이팅 대신 고정 레이팅으로 빠르게 검사."""
import pytest

from gridiron.data.sample import generate_sample_league
from gridiron.domain.models import ScheduledGame
from gridiron.season import owner as O


@pytest.fixture(scope="module")
def setup():
    lg = generate_sample_league(season=2026)
    teams = sorted(lg.teams)
    power = {"ratings": {t: (8.0 if i == 0 else -8.0 if i == 1 else 0.0) for i, t in enumerate(teams)},
             "hfa": 1.5, "sd": 11.0, "games": 544}
    proj = O.project(lg, power, n=120, seed=1)
    return lg, teams, power, proj


def test_projection_orders_teams(setup):
    lg, teams, power, proj = setup
    strong, weak = teams[0], teams[1]
    assert proj[strong]["wins_mean"] > 11 > 6 > proj[weak]["wins_mean"]
    assert proj[strong]["p_playoffs"] > 0.8 > 0.1 > proj[weak]["p_playoffs"]
    assert abs(sum(p["p_title"] for p in proj.values()) - 1.0) < 0.01
    assert O.tier_of(proj[strong]) == "contender" and O.tier_of(proj[weak]) == "rebuild"
    assert O.main_goal(proj[weak]).startswith("wins:")
    assert O.main_goal(proj[strong]) in ("conf_final", "div_round")


def test_confidence_moves_against_expectation(setup):
    lg, teams, power, proj = setup
    strong, weak = teams[0], teams[1]
    st = O.start_season(lg, weak, power=power, projection=proj)
    g = ScheduledGame("x1", 2026, 1, "REG", strong, weak, home_score=10, away_score=20)
    up = O.after_game(st, lg, g)                              # 약팀이 강팀 원정 승리
    g2 = ScheduledGame("x2", 2026, 2, "REG", weak, strong, home_score=10, away_score=20)
    down = O.after_game(st, lg, g2)                           # 예상된 패배
    assert up > 6 and -3 < down < 0
    assert any(m["kind"] == "praise" for m in st.inbox)


def test_warnings_then_firing(setup):
    lg, teams, power, proj = setup
    strong, weak = teams[0], teams[1]
    import copy
    lg = copy.deepcopy(lg)
    st = O.start_season(lg, strong, power=power, projection=proj)
    mine = [g for g in lg.schedule if strong in (g.home, g.away)]
    for w in range(1, 15):
        g = mine[w - 1]
        g.home_score, g.away_score = (0, 30) if g.home == strong else (30, 0)     # 계속 진다
        O.after_game(st, lg, g)
        if st.fired:
            break
    assert st.fired and st.warnings == 3
    warn_weeks = [m["week"] for m in st.inbox if m["kind"] in ("warning", "fired")]
    assert all(b - a >= O.WARN_COOLDOWN for a, b in zip(warn_weeks, warn_weeks[1:]))      # 경고는 3주 간격
    st2 = O.start_season(lg, strong, power=power, projection=proj)
    st2.firing = False
    for w in range(1, 12):
        O.after_game(st2, lg, ScheduledGame(f"m{w}", 2026, w, "REG", strong, weak, home_score=0, away_score=30))
    assert not st2.fired


def test_winning_team_not_fired_midseason(setup):
    """경고 2회를 받았어도 승률 5할 이상이면 시즌 중 해고하지 않는다 (시즌 말 평가로)."""
    lg, teams, power, proj = setup
    strong, weak = teams[0], teams[1]
    st = O.start_season(lg, strong, power=power, projection=proj)
    st.warnings, st.confidence = 2, 15.0
    O._messages(st, 10, -5.0, 0.8, 0.0, win_pct=0.6)
    assert not st.fired
    O._messages(st, 13, -5.0, 0.8, 0.0, win_pct=0.4)
    assert st.fired


def test_owner_saved_and_loaded(tmp_path, setup):
    from gridiron.db.store import load_league, save_league, save_owner, save_team_state
    lg, teams, power, proj = setup
    path = tmp_path / "o.sqlite"
    save_league(lg, path, user_team=teams[2])
    league, user = load_league(path)
    league.owner = O.start_season(league, user, power=power, projection=proj)
    league.owner.confidence = 47.0
    save_owner(path, league)
    save_team_state(path, league)               # 팀 상태 저장이 구단주 상태를 지우면 안 된다
    again, _ = load_league(path)
    assert again.owner is not None and again.owner.confidence == 47.0 and again.owner.main_goal == league.owner.main_goal
