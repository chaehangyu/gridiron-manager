"""로스터 운영 (PRD F3-1·F3-8·F3-8b·F3-8c, M5c)."""
import pytest

from gridiron.data.real_league import load_real_league
from gridiron.domain.models import RosterStatus
from gridiron.season import injuries as INJ
from gridiron.season import roster as R


@pytest.fixture()
def lg():
    return load_real_league(2026)


def test_gameday_48_with_position_minimums(lg):
    for team in ("KC", "BUF", "SF"):
        acts = R.gameday_actives(lg, team)
        assert len(acts) <= 48
        for g, n in R.GAMEDAY_MIN.items():
            have = sum(1 for p in R.healthy(R.active(lg, team)) if R.GROUP_OF[p.position] == g)
            assert sum(1 for p in acts if R.GROUP_OF[p.position] == g) >= min(n, have)


def test_ir_opens_spot_and_ai_fills_it(lg):
    team = "KC"
    excess = R.active(lg, team)[53:]
    for p in excess:
        R.demote(lg, team, p)
    starter = max((p for p in R.active(lg, team) if R.GROUP_OF[p.position] == "CB"), key=R.value)
    INJ.place_ir(lg, starter, 1)
    assert len(R.active(lg, team)) == 52
    moves = R.weekly_moves(lg, [team])[team]
    assert len(R.active(lg, team)) == 53
    assert moves and moves[0].kind in ("sign", "promote")
    assert len(R.practice_squad(lg, team)) >= 16


def test_sign_release_and_limits(lg):
    team = "BUF"
    fa = R.free_agents(lg, "WR")[0]
    ok, why = R.can_sign(lg, team, fa)
    if len(R.active(lg, team)) >= 53:
        assert not ok
        R.release(lg, team, R.active(lg, team)[-1])
    while len(R.active(lg, team)) >= 53:
        R.release(lg, team, R.active(lg, team)[-1])
    assert R.can_sign(lg, team, fa)[0]
    R.sign(lg, team, fa)
    assert fa.team == team and fa.roster_status == RosterStatus.ACTIVE
    R.release(lg, team, fa)
    assert fa.roster_status == RosterStatus.FREE_AGENT and fa.team is None and fa in lg.free_agents()


def test_elevation_limits(lg):
    team = "SF"
    ps = R.practice_squad(lg, team)
    assert R.can_elevate(lg, team, ps[0])[0]
    R.elevate(lg, team, ps[0])
    R.elevate(lg, team, ps[1])
    assert not R.can_elevate(lg, team, ps[2])[0]          # 경기당 2명
    R.clear_elevations(lg, [team])
    ps[0].elevations = 3
    assert not R.can_elevate(lg, team, ps[0])[0]          # 선수당 시즌 3회
    ids = {p.id for p in R.gameday_actives(lg, team)}
    R.elevate(lg, team, ps[1])
    assert ps[1].id in {p.id for p in R.gameday_actives(lg, team)} or len(ids) == 48


def test_qb_shortage_elevates_or_generates(lg):
    team = "KC"
    for p in [p for p in R.active(lg, team) if R.GROUP_OF[p.position] == "QB"]:
        INJ.place_ir(lg, p, 1)
    for p in [p for p in lg.free_agents() if R.GROUP_OF[p.position] == "QB"]:
        p.roster_status = RosterStatus.RETIRED
    R.weekly_moves(lg, [team])
    qbs = [p for p in R.active(lg, team) if R.GROUP_OF[p.position] == "QB"]
    assert len(qbs) >= 2                       # 연습 스쿼드 승격 또는 생성된 대체 선수
