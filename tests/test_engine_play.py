"""원본 Play.test.ts 포팅 (페널티 판정, 연장전, 양 팀 페널티, 경기 진행 이슈)."""
import pytest

from gridiron.engine.skeleton.play import Play


def pen(p, name, pen_yds, t, *, auto=False, spot=None, tack_on=False):
    return {"type": "penalty", "p": p, "automaticFirstDown": auto, "name": name, "penYds": pen_yds,
            "spotYds": spot, "t": t, "tackOn": tack_on}


def setup(game, *, o=0, down=1, to_go=10, scrimmage=20, formation="pass"):
    game.o, game.d = o, 1 - o
    game.down, game.toGo, game.scrimmage = down, to_go, scrimmage
    game.currentPlay = Play(game)
    game.updatePlayersOnField(formation)
    return game.currentPlay


# ── penalty situations ───────────────────────────────────────────────
def test_offensive_penalty_on_pass_applied_against_line_of_scrimmage(init_game_sim):
    game = init_game_sim()
    play = setup(game, scrimmage=19)
    p = game.pickPlayer(game.o)
    assert play.state["current"].scrimmage == 19
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Pass interference", 10, game.o))
    play.addEvent({"type": "pss", "qb": p, "target": p})
    play.addEvent({"type": "pssCmp", "qb": p, "target": p, "yds": 21})
    assert play.state["current"].scrimmage == 40
    play.adjudicatePenalties(False)
    assert play.state["current"].scrimmage == 10  # 골라인까지 절반 거리


def test_penalty_on_kick_return_reflects_kick_over(init_game_sim):
    game = init_game_sim()
    game.o, game.d = 0, 1
    game.awaitingKickoff = 0
    game.currentPlay = Play(game)
    game.updatePlayersOnField("kickoff")
    po, pd = game.pickPlayer(game.o), game.pickPlayer(game.d)
    play = game.currentPlay
    play.addEvent({"type": "k", "p": po, "kickTo": 40})
    play.addEvent({"type": "possessionChange", "yds": 0, "subtype": "kickoff"})
    assert play.state["current"].scrimmage == 40
    play.addEvent(pen(po, "Horse collar tackle", 15, play.state["current"].d, auto=True, spot=4))
    play.addEvent({"type": "kr", "p": pd, "yds": 10})
    assert play.state["current"].scrimmage == 50
    play.commit(False)
    assert play.state["current"].scrimmage == 59
    assert game.awaitingKickoff is None


def test_first_and_ten_after_penalty_on_kick_return(init_game_sim):
    game = init_game_sim()
    game.o, game.d = 0, 1
    game.awaitingKickoff = 0
    game.currentPlay = Play(game)
    game.updatePlayersOnField("kickoff")
    po, pd = game.pickPlayer(game.o), game.pickPlayer(game.d)
    play = game.currentPlay
    play.addEvent({"type": "k", "p": po, "kickTo": 40})
    play.addEvent({"type": "possessionChange", "yds": 0, "subtype": "kickoff"})
    play.addEvent(pen(pd, "Holding", 10, game.d, spot=8))
    play.addEvent({"type": "kr", "p": pd, "yds": 10})
    assert play.state["current"].scrimmage == 50
    play.commit(False)
    assert play.state["current"].scrimmage == 38
    assert game.down == 1
    assert game.toGo == 10


@pytest.mark.parametrize("to_go,final_pts", [(10, 3), (1, 0)])
def test_made_fg_vs_5_yard_penalty(init_game_sim, to_go, final_pts):
    game = init_game_sim()
    play = setup(game, down=4, to_go=to_go, scrimmage=80, formation="fieldGoal")
    p = game.pickPlayer(game.o)
    assert play.state["current"].pts == [0, 0]
    play.addEvent(pen(p, "Too many men on the field", 5, game.d))
    play.addEvent({"type": "fg", "p": p, "made": True, "distance": 100 - 80 + 17, "late": False})
    assert play.state["current"].pts == [3, 0]
    play.adjudicatePenalties(False)
    assert play.state["current"].pts == [final_pts, 0]


def test_made_late_fg_better_than_first_down_penalty(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=4, to_go=1, scrimmage=80, formation="fieldGoal")
    p = game.pickPlayer(game.o)
    play.addEvent(pen(p, "Too many men on the field", 5, game.d))
    play.addEvent({"type": "fg", "p": p, "made": True, "distance": 37, "late": True})
    play.adjudicatePenalties(False)
    assert play.state["current"].pts == [3, 0]


def test_accept_penalty_to_prevent_td(init_game_sim):
    game = init_game_sim()
    play = setup(game, scrimmage=29)
    p = game.pickPlayer(game.o)
    qb = game.getTopPlayerOnField(game.o, "QB")
    target = game.getTopPlayerOnField(game.o, "WR")
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Holding", 10, game.o, spot=0))
    play.addEvent({"type": "pss", "qb": qb, "target": target})
    info = play.addEvent({"type": "pssCmp", "qb": qb, "target": target, "yds": 100 - game.scrimmage})
    assert info["td"] is True
    play.addEvent({"type": "pssTD", "qb": qb, "target": target})
    assert play.state["current"].pts == [6, 0]
    play.adjudicatePenalties(False)
    assert play.state["current"].pts == [0, 0]


def test_automatic_first_down_penalty(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=16, scrimmage=24)
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Unnecessary roughness", 15, game.d, auto=True, spot=0, tack_on=True))
    play.addEvent({"type": "pss", "qb": p, "target": p})
    play.addEvent({"type": "pssInc", "defender": None})
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage) == (1, 10, 39)


def test_offense_penalty_on_made_xp_accepted(init_game_sim):
    game = init_game_sim()
    play = setup(game, scrimmage=90, formation="fieldGoal")
    p = game.pickPlayer(game.o)
    play.addEvent(pen(p, "Unnecessary roughness", 15, game.o, spot=0, tack_on=True))
    play.addEvent({"type": "xp", "p": p, "distance": 33, "made": True})
    assert play.state["current"].pts == [1, 0]
    play.adjudicatePenalties(False)
    assert play.state["current"].pts == [0, 0]


def test_offense_penalty_on_missed_xp_declined(init_game_sim):
    game = init_game_sim()
    game.awaitingKickoff = None
    play = setup(game, scrimmage=90, formation="fieldGoal")
    p = game.pickPlayer(game.o)
    play.addEvent(pen(p, "Unnecessary roughness", 15, game.o, spot=0, tack_on=True))
    play.addEvent({"type": "xp", "p": p, "distance": 33, "made": False})
    assert play.state["current"].awaitingKickoff == 0
    play.adjudicatePenalties(False)
    assert play.state["current"].awaitingKickoff == 0


def test_offensive_penalty_on_pass_down_does_not_increase(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=2, scrimmage=28)
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Holding", 10, game.o, spot=4))
    play.addEvent({"type": "pss", "qb": p, "target": p})
    play.addEvent({"type": "pssCmp", "qb": p, "target": p, "yds": 6})
    assert play.state["current"].down == 3
    play.commit(False)
    assert play.state["current"].down == 2


def test_defense_prefers_fourth_down_over_third(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=3, to_go=10, scrimmage=40)
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Holding", 10, game.o))
    play.addEvent({"type": "pss", "qb": p, "target": p})
    play.addEvent({"type": "pssInc", "defender": p})
    assert play.state["current"].down == 4
    play.commit(False)
    assert play.state["current"].down == 4


def test_roughing_the_passer_adds_to_end_and_stats_persist(init_game_sim):
    game = init_game_sim()
    play = setup(game, scrimmage=20)
    po, pd = game.pickPlayer(game.o), game.pickPlayer(game.d)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(pd, "Roughing the passer", 15, game.d, auto=True, spot=10, tack_on=True))
    play.addEvent({"type": "pss", "qb": po, "target": po})
    play.addEvent({"type": "pssCmp", "qb": po, "target": po, "yds": 10})
    assert play.state["current"].scrimmage == 30
    assert po.stat["pssYds"] == 10
    play.adjudicatePenalties(False)
    assert play.state["current"].scrimmage == 45
    assert po.stat["pssYds"] == 10


def test_penalty_during_extra_point(init_game_sim):
    game = init_game_sim()
    game.awaitingAfterTouchdown = True
    play = setup(game, down=5, to_go=10, scrimmage=103)
    p = game.pickPlayer(game.o)
    play.addEvent(pen(p, "False start", 5, game.o))
    play.commit(False)
    assert game.awaitingAfterTouchdown is True
    assert game.o == 0


def test_penalty_on_punt_first_down_keeps_current_drive(init_game_sim):
    game = init_game_sim()
    game.currentDrive = 0
    play = setup(game, scrimmage=20, formation="punt")
    pd = game.pickPlayer(game.d)
    assert play.state["initial"].currentDrive == 0
    play.addEvent({"type": "possessionChange", "subtype": "punt", "yds": 0})
    assert play.state["current"].currentDrive is None
    play.addEvent(pen(pd, "Unnecessary roughness", 15, game.d, auto=True, spot=10, tack_on=True))
    play.adjudicatePenalties(False)
    assert play.state["current"].currentDrive == 0


# ── overtime ─────────────────────────────────────────────────────────
def init_overtime(init_game_sim, overtime_type):
    game = init_game_sim()
    game.o, game.d = 0, 1
    game.team[0].stat["ptsQtrs"] = [0, 0, 0, 0, 0]
    game.team[1].stat["ptsQtrs"] = [0, 0, 0, 0, 0]
    game.overtimeType = overtime_type
    return game


@pytest.mark.parametrize("ot_type,expected", [("suddenDeath", "over"), ("exceptFg", "over"),
                                              ("bothPossess", "firstPossession")])
def test_touchdown_on_first_possession(init_game_sim, ot_type, expected):
    game = init_overtime(init_game_sim, ot_type)
    game.overtimeState = "firstPossession"
    game.currentPlay = Play(game)
    game.updatePlayersOnField("run")
    p = game.pickPlayer(game.o)
    game.currentPlay.addEvent({"type": "rusTD", "p": p})
    game.currentPlay.commit(False)
    assert game.overtimeState == expected


@pytest.mark.parametrize("ot_type,expected", [("suddenDeath", "over"), ("exceptFg", "firstPossession"),
                                              ("bothPossess", "firstPossession")])
def test_fg_on_first_possession(init_game_sim, ot_type, expected):
    game = init_overtime(init_game_sim, ot_type)
    game.overtimeState = "firstPossession"
    game.currentPlay = Play(game)
    game.updatePlayersOnField("fieldGoal")
    p = game.pickPlayer(game.o)
    game.currentPlay.addEvent({"type": "fg", "p": p, "distance": 30, "made": True, "late": False})
    game.currentPlay.commit(False)
    assert game.overtimeState == expected


@pytest.mark.parametrize("ot_type", ["exceptFg", "bothPossess"])
def test_fg_on_second_possession(init_game_sim, ot_type):
    game = init_overtime(init_game_sim, ot_type)
    game.overtimeState = "secondPossession"
    game.currentPlay = Play(game)
    game.updatePlayersOnField("fieldGoal")
    p = game.pickPlayer(game.o)
    game.currentPlay.addEvent({"type": "fg", "p": p, "distance": 30, "made": True, "late": False})
    game.currentPlay.commit(False)
    assert game.overtimeState == "over"


@pytest.mark.parametrize("ot_type", ["suddenDeath", "exceptFg", "bothPossess"])
def test_safety_on_first_possession_over(init_game_sim, ot_type):
    game = init_overtime(init_game_sim, ot_type)
    game.overtimeState = "firstPossession"
    game.currentPlay = Play(game)
    game.updatePlayersOnField("run")
    p = game.pickPlayer(game.d)
    game.currentPlay.addEvent({"type": "defSft", "p": p})
    game.currentPlay.commit(False)
    assert game.overtimeState == "over"


def test_touchdown_negated_by_penalty_not_over(init_game_sim):
    game = init_overtime(init_game_sim, "suddenDeath")
    game.overtimeState = "firstPossession"
    game.currentPlay = Play(game)
    game.updatePlayersOnField("run")
    p = game.pickPlayer(game.o)
    game.currentPlay.addEvent(pen(p, "Holding", 10, game.o, spot=0))
    game.currentPlay.addEvent({"type": "rusTD", "p": p})
    game.currentPlay.commit(False)
    assert game.overtimeState == "firstPossession"


@pytest.mark.parametrize("made,expected", [(True, "bothTeamsPossessed"), (False, "over")])
def test_missed_xp_and_losing_over(init_game_sim, made, expected):
    game = init_overtime(init_game_sim, "bothPossess")
    game.team[0].stat["pts"] = 6
    game.team[1].stat["pts"] = 7
    game.overtimeState = "bothTeamsPossessed"
    game.currentPlay = Play(game)
    game.updatePlayersOnField("run")
    p = game.pickPlayer(game.o)
    game.currentPlay.addEvent({"type": "xp", "p": p, "distance": 35, "made": made})
    game.currentPlay.commit(False)
    assert game.overtimeState == expected


# ── one penalty on each team ─────────────────────────────────────────
def test_15_yard_penalty_overrules_5_yard(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=7, scrimmage=35)
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Taunting", 15, game.o, spot=4, tack_on=True))
    play.addEvent(pen(p, "Holding", 5, game.d, auto=True))
    play.addEvent({"type": "pss", "qb": p, "target": p})
    play.addEvent({"type": "pssCmp", "qb": p, "target": p, "yds": 4})
    assert play.state["current"].scrimmage == 39
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage) == (2, 22, 20)


def test_two_penalties_after_change_of_possession_roll_back(init_game_sim):
    game = init_game_sim()
    game.o, game.d = 0, 1
    game.awaitingKickoff = 0
    game.currentPlay = Play(game)
    game.updatePlayersOnField("kickoff")
    po, pd = game.pickPlayer(game.o), game.pickPlayer(game.d)
    play = game.currentPlay
    play.addEvent({"type": "k", "p": po, "kickTo": 40})
    play.addEvent({"type": "possessionChange", "yds": 0, "subtype": "kickoff"})
    play.addEvent(pen(po, "Holding", 10, game.o, spot=-3))
    play.addEvent(pen(pd, "Holding", 5, game.d, auto=True))
    play.addEvent({"type": "kr", "p": pd, "yds": 10})
    assert play.state["current"].scrimmage == 50
    play.commit(False)
    assert play.state["current"].scrimmage == 40
    assert game.awaitingKickoff is None


def test_penalty_offense_change_of_possession_penalty_new_offense(init_game_sim):
    game = init_game_sim()
    game.o, game.d = 0, 1
    game.awaitingKickoff = 0
    game.currentPlay = Play(game)
    game.updatePlayersOnField("kickoff")
    po, pd = game.pickPlayer(game.o), game.pickPlayer(game.d)
    play = game.currentPlay
    play.addEvent(pen(po, "Holding", 10, game.o, spot=-3))
    play.addEvent({"type": "k", "p": po, "kickTo": 40})
    play.addEvent({"type": "possessionChange", "yds": 0, "subtype": "kickoff"})
    assert play.state["current"].scrimmage == 40
    play.addEvent(pen(pd, "Holding", 5, game.d, auto=True, spot=0))
    play.addEvent({"type": "kr", "p": pd, "yds": 10})
    assert play.state["current"].scrimmage == 50
    play.commit(False)
    assert play.state["current"].scrimmage == 35
    assert game.awaitingKickoff is None
    assert game.o == 1


def test_offsetting_penalties_replay_down(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=7, scrimmage=80)
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Holding", 10, game.o, spot=-3))
    play.addEvent(pen(p, "Holding", 5, game.d, auto=True))
    play.addEvent({"type": "rus", "p": p, "yds": 20})
    play.addEvent({"type": "rusTD", "p": p})
    assert play.state["current"].scrimmage == 100
    assert play.state["current"].pts == [6, 0]
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage, cur.pts) == (2, 7, 80, [0, 0])


def test_offsetting_penalties_roll_back_play(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=7, scrimmage=25)
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Holding", 10, game.o, spot=-3))
    play.addEvent(pen(p, "Holding", 5, game.d, auto=True))
    play.addEvent({"type": "pss", "qb": p, "target": p})
    play.addEvent({"type": "pssCmp", "qb": p, "target": p, "yds": 21})
    assert play.state["current"].scrimmage == 46
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage) == (2, 7, 25)


def test_offsetting_penalties_take_score_off_board(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=7, scrimmage=80)
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Holding", 10, game.o, spot=-3))
    play.addEvent(pen(p, "Holding", 5, game.d, auto=True))
    play.addEvent({"type": "pss", "qb": p, "target": p})
    info = play.addEvent({"type": "pssCmp", "qb": p, "target": p, "yds": 100 - game.scrimmage})
    assert info["td"] is True
    play.addEvent({"type": "pssTD", "qb": p, "target": p})
    assert play.state["current"].pts == [6, 0]
    assert [game.team[0].stat["pts"], game.team[1].stat["pts"]] == [6, 0]
    play.adjudicatePenalties(False)
    assert play.state["current"].pts == [0, 0]
    assert [game.team[0].stat["pts"], game.team[1].stat["pts"]] == [0, 0]
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage, cur.pts) == (2, 7, 80, [0, 0])


def test_tack_on_offsetting_penalties_replay_down(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=1, to_go=10, scrimmage=25)
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent(pen(p, "Holding", 10, game.o, spot=21, tack_on=True))
    play.addEvent(pen(p, "Holding", 5, game.d, auto=True))
    play.addEvent({"type": "pss", "qb": p, "target": p})
    play.addEvent({"type": "pssCmp", "qb": p, "target": p, "yds": 21})
    assert play.state["current"].scrimmage == 46
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage) == (1, 10, 25)


# ── game sim issues ──────────────────────────────────────────────────
def test_missed_fg_possession_change(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=7, scrimmage=63, formation="fieldGoal")
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "fg", "p": p, "made": False, "distance": 54, "late": False})
    play.addEvent({"type": "possessionChange", "subtype": "missedFg", "yds": -7})
    play.commit(False)
    cur = play.state["current"]
    assert (cur.o, cur.down, cur.toGo, cur.scrimmage) == (1, 1, 10, 44)


def test_run_fumble_recovered_by_offense_lost_down(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=7, scrimmage=63, formation="fieldGoal")
    pf, pforced = game.pickPlayer(game.o), game.pickPlayer(game.d)
    play.addEvent({"type": "rus", "p": pf, "yds": 2})
    play.addEvent({"type": "fmb", "pFumbled": pf, "pForced": pforced, "yds": 1})
    play.addEvent({"type": "fmbRec", "pFumbled": pf, "pRecovered": pf, "yds": 1, "lost": False})
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage) == (3, 3, 67)


def test_pass_fumble_recovered_by_offense_lost_down(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=7, scrimmage=63, formation="fieldGoal")
    pf, pforced = game.pickPlayer(game.o), game.pickPlayer(game.d)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent({"type": "fmb", "pFumbled": pf, "pForced": pforced, "yds": 1})
    play.addEvent({"type": "fmbRec", "pFumbled": pf, "pRecovered": pf, "yds": 1, "lost": False})
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage) == (3, 5, 65)


def test_qb_scramble_counts_as_one_down(init_game_sim):
    game = init_game_sim()
    play = setup(game, down=2, to_go=7, scrimmage=63, formation="fieldGoal")
    p = game.pickPlayer(game.o)
    play.addEvent({"type": "dropback", "pbw": {}})
    play.addEvent({"type": "rus", "p": p, "yds": 2})
    play.commit(False)
    cur = play.state["current"]
    assert (cur.down, cur.toGo, cur.scrimmage) == (3, 5, 65)
