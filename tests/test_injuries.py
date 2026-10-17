"""부상 관리 (PRD F10, M5b)."""
from gridiron.data.sample import generate_sample_league
from gridiron.domain.models import RosterStatus, ScheduledGame
from gridiron.engine.injury import InjuryModel, durability_mult
from gridiron.engine.skeleton.rng import Rng
from gridiron.engine.skeleton.types import PlayerGameSim
from gridiron.season import injuries as INJ


def _league():
    lg = generate_sample_league(season=2026)
    team = next(iter(lg.teams))
    p = next(p for p in lg.roster(team) if p.position.value == "WR")
    return lg, team, p


def _week_games(lg, team):
    return {g.week for g in lg.schedule if team in (g.home, g.away)}


def test_injury_progression_out_questionable_heal():
    lg, team, p = _league()
    weeks = sorted(_week_games(lg, team))
    w0 = weeks[0]
    g = ScheduledGame("g1", 2026, w0, "REG", team, "XXX")
    INJ.apply_game(lg, g, [{"pid": p.id, "part": "hamstring", "missed": 2, "season_out": False}])
    inj = p.injury
    assert inj.weeks_out_min <= 2 <= inj.weeks_out_max and inj.type
    INJ.after_week(lg, w0, {team})                 # 다친 주는 차감하지 않는다
    statuses = []
    for w in weeks[1:5]:
        INJ.weekly_report(lg, w)
        statuses.append(p.injury.status if p.injury else "healthy")
        if statuses[-1] == "questionable":
            assert p.rust_games == 1 and p.hurt          # 복귀전: 경기 감각 페널티 + 부상 안고 출전
        assert p.injured == (p.injury is not None and p.injury.weeks_remaining > 0)
        INJ.after_week(lg, w, {team})
    assert statuses[0] in ("out", "doubtful") and statuses[1] in ("out", "doubtful")
    assert statuses[2] == "questionable" and statuses[3] == "healthy"
    assert p.rust_games == 0 and p.reinjury_until > weeks[3]


def test_bye_week_does_not_heal():
    lg, team, p = _league()
    g = ScheduledGame("g1", 2026, 1, "REG", team, "XXX")
    INJ.apply_game(lg, g, [{"pid": p.id, "part": "ankle", "missed": 1, "season_out": False}])
    INJ.after_week(lg, 2, set())                  # 우리 팀 경기 없음
    assert p.injury.weeks_remaining == 1


def test_ir_rules():
    lg, team, p = _league()
    weeks = sorted(_week_games(lg, team))
    g = ScheduledGame("g1", 2026, weeks[0], "REG", team, "XXX")
    INJ.apply_game(lg, g, [{"pid": p.id, "part": "knee", "missed": 6, "season_out": False}])
    p.injury.weeks_out_min = 5
    moves = INJ.auto_ir(lg, weeks[0], {team})
    assert (team, p, "ir") in moves and p.roster_status == RosterStatus.IR
    ok, why = INJ.can_activate(lg, p, weeks[2])
    assert not ok
    for w in weeks[:5]:
        for gg in lg.schedule:
            if gg.week == w and team in (gg.home, gg.away):
                gg.home_score, gg.away_score = 10, 7
    p.injury.weeks_remaining = 0
    ok, why = INJ.can_activate(lg, p, weeks[4])
    assert ok, why
    INJ.activate(lg, p, weeks[4])
    assert p.roster_status == RosterStatus.ACTIVE and lg.ir_returns_used[team] == 1


def test_repeat_concussion_longer():
    lg, team, p = _league()
    g = ScheduledGame("g1", 2026, 1, "REG", team, "XXX")
    INJ.apply_game(lg, g, [{"pid": p.id, "part": "concussion", "missed": 1, "season_out": False}])
    first = p.injury.weeks_remaining
    INJ.apply_game(lg, g, [{"pid": p.id, "part": "concussion", "missed": 1, "season_out": False}])
    assert p.injury.weeks_remaining == first + 1


def test_engine_hazard_and_no_concussion_return():
    m = InjuryModel()
    a = PlayerGameSim("a", "A", "RB", 26, {}, {}, attributes={"recovery": 10}, inj_mult=durability_mult(5))
    b = PlayerGameSim("b", "B", "RB", 26, {}, {}, attributes={"recovery": 10}, inj_mult=durability_mult(18))
    assert m.hazard(a, 1.0)[0] > m.hazard(b, 1.0)[0]
    assert m.hazard(a, 0.2)[0] > m.hazard(a, 1.0)[0]
    rng = Rng(1)
    assert not m.may_return(a, {"missed": 0, "part": "concussion"}, 0, rng)
    assert not m.may_return(a, {"missed": 2, "part": "ankle"}, 0, rng)
    draws = [m.draw(a, rng) for _ in range(400)]
    assert 0.3 < sum(d["missed"] == 0 for d in draws) / 400 < 0.55


def test_injuries_saved_and_loaded(tmp_path):
    from gridiron.db.store import load_league, save_league, save_team_state
    lg, team, p = _league()
    path = tmp_path / "s.sqlite"
    save_league(lg, path, user_team=team)
    league, _ = load_league(path)
    q = league.players[p.id]
    g = ScheduledGame("g1", 2026, 1, "REG", team, "XXX")
    INJ.apply_game(league, g, [{"pid": q.id, "part": "ankle", "missed": 3, "season_out": False}])
    INJ.place_ir(league, q, 1)
    league.ir_returns_used[team] = 2
    save_team_state(path, league)
    again, _ = load_league(path)
    r = again.players[p.id]
    assert r.injury and r.injury.weeks_remaining == 3 and r.injury.type == q.injury.type
    assert r.roster_status == RosterStatus.IR and r.ir_week == 1 and again.ir_returns_used[team] == 2
    r.injury = None
    save_team_state(path, again)
    third, _ = load_league(path)
    assert third.players[p.id].injury is None
