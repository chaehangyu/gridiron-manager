"""원본 index.test.ts 포팅 + 결정론·통계 범위 확인."""
from gridiron.engine.adapter import build_team
from gridiron.engine.skeleton.game import GameSim
from gridiron.engine.skeleton.play import Play


def late_game(game, *, pts0, pts1, qtrs, scrimmage, clock, down=1):
    game.awaitingKickoff = None
    game.o, game.d = 0, 1
    game.team[0].stat["pts"] = pts0
    game.team[0].stat["ptsQtrs"] = [0] * (qtrs - 1) + [pts0]
    game.team[1].stat["pts"] = pts1
    game.team[1].stat["ptsQtrs"] = [0] * (qtrs - 1) + [pts1]
    game.scrimmage = scrimmage
    game.clock = clock
    game.down = down
    game.currentPlay = Play(game)


def test_fg_when_down_2_at_end_with_little_time(init_game_sim):
    game = init_game_sim()
    late_game(game, pts0=0, pts1=2, qtrs=4, scrimmage=80, clock=0.01)
    assert game.getPlayType() == "fieldGoalLate"


def test_fg_on_4th_down_to_take_lead_late(init_game_sim):
    game = init_game_sim()
    game.probMadeFieldGoal = lambda kicker=None: 0.75
    for pts_down in (2, 1, 0, -4, -5, -6, -7, -8):
        late_game(game, pts0=10, pts1=10 + pts_down, qtrs=4, scrimmage=80, clock=2, down=4)
        assert game.getPlayType() == "fieldGoal", pts_down


def test_fg_at_end_of_second_quarter(init_game_sim):
    game = init_game_sim()
    late_game(game, pts0=14, pts1=24, qtrs=2, scrimmage=80, clock=0.01)
    assert game.getPlayType() == "fieldGoalLate"


def test_fg_at_end_of_overtime_tie(init_game_sim):
    game = init_game_sim()
    late_game(game, pts0=21, pts1=21, qtrs=4, scrimmage=80, clock=3 / 60)
    game.team[0].stat["ptsQtrs"].append(0)
    game.team[1].stat["ptsQtrs"].append(0)
    game.overtimes = 1
    game.overtimeState = "bothTeamsPossessed"
    assert game.getPlayType() == "fieldGoalLate"


def test_overtime_fg_only_when_it_wins(init_game_sim):
    game = init_game_sim()
    late_game(game, pts0=21, pts1=21, qtrs=4, scrimmage=90, clock=10)
    game.team[0].stat["ptsQtrs"].append(0)
    game.team[1].stat["ptsQtrs"].append(0)
    game.overtimes = 1
    game.overtimeState = "firstPossession"
    game.probMadeFieldGoal = lambda kicker=None: 0.99
    assert game.getPlayType() != "fieldGoal"
    game.overtimeState = "bothTeamsPossessed"
    assert game.getPlayType() == "fieldGoal"


def test_dont_punt_when_down_late_and_usually_pass(init_game_sim):
    game = init_game_sim()
    late_game(game, pts0=0, pts1=7, qtrs=4, scrimmage=20, clock=1.5, down=4)
    num_run = 0
    for _ in range(100):
        pt = game.getPlayType()
        assert pt in ("run", "pass")
        num_run += pt == "run"
    assert num_run <= 10


def _no_randomness(game):
    game.probFumble = lambda p: 0
    game.checkPenalties = lambda *a, **k: False


def test_sack_on_4th_down_recorded_on_correct_team(init_game_sim):
    game = init_game_sim()
    late_game(game, pts0=0, pts1=0, qtrs=1, scrimmage=20, clock=10, down=4)
    game.outcome.prob_sack = lambda g, qb: 1
    _no_randomness(game)
    game.doPass()
    game.currentPlay.commit(False)
    assert game.team[0].stat["defSk"] == 0
    assert game.team[1].stat["defSk"] == 1
    assert (game.o, game.d) == (1, 0)


def test_interception_on_4th_down(init_game_sim):
    game = init_game_sim()
    late_game(game, pts0=0, pts1=0, qtrs=1, scrimmage=20, clock=10, down=4)
    game.toGo = 1
    game.currentPlay = Play(game)
    game.outcome.prob_sack = lambda g, qb: 0
    game.outcome.prob_int = lambda g, qb, d: 1
    game.outcome.prob_scramble = lambda g, qb: 0
    _no_randomness(game)
    game.doPass()
    game.currentPlay.commit(False)
    assert game.team[0].stat["defInt"] == 0
    assert game.team[1].stat["defInt"] == 1
    assert (game.o, game.d) == (1, 0)


def test_ot_ends_after_failed_4th_down_if_first_team_kicked_fg(init_game_sim):
    game = init_game_sim()
    late_game(game, pts0=0, pts1=3, qtrs=5, scrimmage=20, clock=1.5, down=4)
    game.overtimeState = "secondPossession"
    game.getPlayType = lambda: "pass"
    game.outcome.prob_sack = lambda g, qb: 1
    _no_randomness(game)
    game.simPlay()
    assert game.overtimeState == "over"
    assert (game.o, game.d) == (1, 0)


def test_fumble_recovered_by_offense_costs_one_down(init_game_sim):
    game = init_game_sim(seed=3)
    game.checkPenalties = lambda *a, **k: False
    game.getPlayType = lambda: "run"
    for _ in range(500):
        game.awaitingKickoff = None
        game.awaitingAfterTouchdown = False
        game.o, game.d = 0, 1
        game.down, game.toGo, game.scrimmage, game.clock = 1, 10, 20, 20
        state = {"fumbled": False}

        def one_fumble(p, state=state):
            if state["fumbled"]:
                return 0
            state["fumbled"] = True
            return 1

        game.probFumble = one_fumble
        game.simPlay()
        if game.o == 0 and game.scrimmage < 30 and not game.awaitingAfterTouchdown:
            break
    assert game.down == 2
    assert (game.o, game.d) == (0, 1)


# ── 추가: 결정론·전체 경기 ─────────────────────────────────────────────
def _play(sample_league, seed):
    abbrs = sorted(sample_league.teams)[:2]
    day = sample_league.season_start()
    teams = [build_team(sample_league, abbrs[0], 0, day), build_team(sample_league, abbrs[1], 1, day)]
    res = GameSim(teams, seed=seed, do_play_by_play=True).run()
    return [t.stat["pts"] for t in res["team"]], len(res["playByPlay"])


def test_same_seed_same_result(sample_league):
    assert _play(sample_league, 42) == _play(sample_league, 42)


def test_full_game_scores_consistent(sample_league):
    abbrs = sorted(sample_league.teams)[:2]
    day = sample_league.season_start()
    for seed in range(20):
        teams = [build_team(sample_league, abbrs[0], 0, day), build_team(sample_league, abbrs[1], 1, day)]
        res = GameSim(teams, seed=seed).run()
        for t in res["team"]:
            assert t.stat["pts"] == sum(t.stat["ptsQtrs"])
            assert 0 <= t.stat["pts"] < 90
        # 정규시즌은 연장 최대 1회
        assert res["overtimes"] <= 1
