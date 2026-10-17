"""스카우팅 파악도·정보 공개 (PRD F13)와 역할 평가 (F2-6)."""
from gridiron.data.sample import generate_sample_league
from gridiron.domain.attributes import HIDDEN_KEYS
from gridiron.ratings.roles import best_role, role_ratings
from gridiron.season import knowledge as KN


def _setup():
    lg = generate_sample_league(season=2026)
    me, other = sorted(lg.teams)[:2]
    return lg, me, other


def test_ranges_contain_truth_and_are_stable():
    lg, me, other = _setup()
    p = lg.roster(other)[0]
    k = KN.knowledge(lg, p, me)
    assert 20 <= k <= 40
    for key, v in p.attributes.items():
        r = KN.attr_range(lg, p, key, me)
        if key in HIDDEN_KEYS:
            assert r is None
            continue
        lo, hi = r
        assert lo - 0.5 <= v <= hi + 0.5 and hi - lo <= 10
        assert KN.attr_range(lg, p, key, me) == r            # 볼 때마다 같은 범위
    lo, hi = KN.pr_range(lg, p, me)
    lg.knowledge[p.id] = 100.0
    lo2, hi2 = KN.pr_range(lg, p, me)
    assert lo2 == hi2 and lo <= lo2 <= hi


def test_own_players_exact_and_knowledge_grows():
    lg, me, other = _setup()
    mine = lg.roster(me)[0]
    assert KN.knowledge(lg, mine, me) == 100 and KN.attr_range(lg, mine, "speed", me)[0] == mine.attributes["speed"]
    g = next(g for g in lg.schedule if {g.home, g.away} == {me, other} or (me in (g.home, g.away)))
    opp = g.away if g.home == me else g.home
    p = lg.roster(opp)[0]
    before = KN.knowledge(lg, p, me)
    g.home_score, g.away_score = 20, 10
    KN.weekly_update(lg, me, g.week)
    assert KN.knowledge(lg, p, me) >= before + 20


def test_hidden_comments_after_four_weeks():
    lg, me, _ = _setup()
    p = lg.roster(me)[0]
    p.attributes["durability"] = 17
    assert "4주" in KN.hidden_comments(p, 1)[0]
    assert "부상에 강함" in KN.hidden_comments(p, 5)


def test_roles():
    lg, me, _ = _setup()
    cb = next(p for p in lg.roster(me) if p.position.value == "CB")
    rr = role_ratings(cb)
    assert set(rr) == {"press_man", "zone", "slot"}
    cb.attributes.update(press=20, man_coverage=20, zone_coverage=3, ball_skills=3)
    assert best_role(cb)[0] == "press_man"
    k = next(p for p in lg.roster(me) if p.position.value == "K")
    assert role_ratings(k) == {} and best_role(k) is None
