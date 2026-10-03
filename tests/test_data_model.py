"""M2: 실측 기준 분포·판단 모델·실측 결과 모델 테스트."""
from collections import Counter
from statistics import mean

import pytest

from gridiron.baseline.tables import lookup, sample_quantile, tables
from gridiron.engine import models_ml as M
from gridiron.engine.adapter import build_team
from gridiron.engine.norms import compute_norms
from gridiron.engine.outcome.data_model import DataOutcome, dd_class, zone_of
from gridiron.engine.skeleton.game import GameSim
from gridiron.engine.skeleton.play import Play
from gridiron.engine.skeleton.settings import GameSettings


# ── 테이블 ─────────────────────────────────────────────────────────
def test_lookup_falls_back_to_coarser_cell():
    detailed = lookup("pass_rates", "deep", 0, 1, "open", 0, "C0")
    assert 0.2 < detailed["cmp"] < 0.5
    coarse = lookup("pass_rates", "deep", 0, 1, "open", 0, "NOPE")  # 없는 커버리지 → 상위 칸
    assert coarse["n"] >= detailed["n"]


def test_quantile_shift_moves_distribution():
    q = lookup("run", "inside", "open", "normal", "std")["q"]
    assert sample_quantile(q, 0.5, -0.5) < sample_quantile(q, 0.5) < sample_quantile(q, 0.5, 0.5)
    assert sample_quantile(q, 0.0) == q[0] and sample_quantile(q, 1.0) == q[-1]


def test_measured_structure_present():
    t = tables()
    assert 0.25 < t["pressure_overall"] < 0.35
    assert t["depth_ratio_cov"]["C2"]["quick"] > 1 > t["depth_ratio_cov"]["C2"]["deep"]
    blitz = lookup("pressure", "C1", 1, 0)
    no_blitz = lookup("pressure", "C1", 0, 0)
    assert blitz > no_blitz
    fg = t["special"]["fg_make_by_yard"]
    assert fg["30"] > fg["45"] > fg["55"]


def test_situation_buckets():
    assert dd_class(1, 10) == "1st" and dd_class(3, 1) == "3s" and dd_class(3, 9) == "3l"
    assert zone_of(95) == "backed" and zone_of(50) == "open" and zone_of(12) == "red" and zone_of(3) == "goal"


# ── EP·WP·xpass ────────────────────────────────────────────────────
def test_ep_monotonic_in_field_position():
    assert M.ep(1, 10, 90) < M.ep(1, 10, 50) < M.ep(1, 10, 10)
    assert M.ep(3, 15, 50) < M.ep(1, 10, 50)


def test_wp_behaves():
    base = dict(game_seconds_remaining=1800, half_seconds_remaining=1800, ep_value=1.0, pos_timeouts=3,
                def_timeouts=3, home=True)
    assert M.wp(-7, **base) < M.wp(0, **base) < M.wp(7, **base)
    late = dict(base, game_seconds_remaining=60, half_seconds_remaining=60)
    assert M.wp(7, **late) > M.wp(7, **base) > 0.5


def test_xpass_situations():
    assert M.xpass(3, 10, 60, 0, 2000, 1000, 0.5) > M.xpass(1, 10, 60, 0, 2000, 1000, 0.5) > M.xpass(3, 1, 60, 0, 2000, 1000, 0.5)
    assert M.xpass(1, 10, 60, -14, 200, 200, 0.05) > M.xpass(1, 10, 60, 14, 200, 200, 0.95)


# ── 게임 ───────────────────────────────────────────────────────────
@pytest.fixture
def data_game(sample_league):
    norms = compute_norms(sample_league)

    def make(seed=0, outcome=None):
        abbrs = sorted(sample_league.teams)[:2]
        day = sample_league.season_start()
        teams = [build_team(sample_league, abbrs[0], 0, day), build_team(sample_league, abbrs[1], 1, day)]
        return GameSim(teams, settings=GameSettings.from_config(), outcome=outcome or DataOutcome.for_league(sample_league), seed=seed,
                       norms=norms)

    return make


def _fourth(game, *, scrimmage, to_go, pts=(0, 0), clock=10.0, qtrs=2):
    game.awaitingKickoff = None
    game.o, game.d = 0, 1
    game.team[0].stat["pts"], game.team[1].stat["pts"] = pts
    game.team[0].stat["ptsQtrs"] = [0] * (qtrs - 1) + [pts[0]]
    game.team[1].stat["ptsQtrs"] = [0] * (qtrs - 1) + [pts[1]]
    game.down, game.toGo, game.scrimmage, game.clock = 4, to_go, scrimmage, clock
    game.currentPlay = Play(game)
    return game.outcome.fourth_down_decision(game)


def test_fourth_down_decisions(data_game):
    game = data_game()
    assert _fourth(game, scrimmage=30, to_go=10) == "punt"          # 자기 진영 30, 4th & 10
    assert _fourth(game, scrimmage=88, to_go=6) == "fieldGoal"      # 상대 12야드, 4th & 6
    assert _fourth(game, scrimmage=62, to_go=1) == "go"             # 상대 38야드, 4th & 1
    # 4쿼터 막판 7점 뒤지면 자기 진영에서도 공격 (펀트 안 함)
    assert _fourth(game, scrimmage=40, to_go=6, pts=(10, 17), clock=1.5, qtrs=4) == "go"


def test_data_model_game_deterministic(data_game):
    a = data_game(seed=9).run()
    b = data_game(seed=9).run()
    assert [t.stat["pts"] for t in a["team"]] == [t.stat["pts"] for t in b["team"]]


def test_wp_series_and_state_values(data_game):
    game = data_game(seed=1)
    game.playByPlay.active = True
    game.run()
    assert len(game.wp_series) > 100
    assert all(0 <= wp <= 1 for _, _, wp in game.wp_series)
    clocks = [e for e in game.playByPlay.events if e["type"] == "clock" and e.get("ep") is not None]
    assert clocks and all(-3 < e["ep"] < 7.5 for e in clocks)


def test_league_averages_in_broad_bands(sample_league):
    """PRD §8.4 보정 목표 (표본이 작아 범위를 넓게 잡는다; 정밀 점검은 tools/check_engine_stats.py)."""
    norms = compute_norms(sample_league)
    tot = Counter()
    n = 80
    for i in range(n):
        g = sample_league.schedule[i]
        res = GameSim([build_team(sample_league, g.home, 0, g.gameday), build_team(sample_league, g.away, 1, g.gameday)],
                      settings=GameSettings.from_config(), outcome=DataOutcome.for_league(sample_league), seed=i,
                      norms=norms).run()
        for t in res["team"]:
            for k in ("pts", "pss", "pssCmp", "pssSk", "rus", "rusYds", "pssInt"):
                tot[k] += t.stat[k]
    tg = 2 * n
    assert 17 <= tot["pts"] / tg <= 26
    assert 0.60 <= tot["pssCmp"] / tot["pss"] <= 0.71
    assert 3.8 <= tot["rusYds"] / tot["rus"] <= 4.9
    assert 0.04 <= tot["pssSk"] / (tot["pss"] + tot["pssSk"]) <= 0.09


def test_better_pass_rush_creates_more_pressure(sample_league):
    """능력치 방향성: 패스 러시를 크게 올리면 압박률이 오른다 (ENGINE_DESIGN G1의 기초)."""
    norms = compute_norms(sample_league)

    def pressure_rate(boost: float) -> float:
        rates = []

        class Probe(DataOutcome):
            def pass_play(self, g):
                plan = super().pass_play(g)
                if "pressure" in plan.extra and g.d == 1:
                    rates.append(plan.extra["pressure"])
                return plan

        abbrs = sorted(sample_league.teams)[:2]
        day = sample_league.season_start()
        for seed in range(12):
            home = build_team(sample_league, abbrs[0], 0, day)
            away = build_team(sample_league, abbrs[1], 1, day)
            for p in away.players:
                if p.pos == "DL":
                    for k in ("power_rush", "finesse_rush"):
                        p.attributes[k] = min(20, p.attributes[k] + boost)
            GameSim([home, away], settings=GameSettings.from_config(), outcome=Probe(), seed=seed, norms=norms).run()
        return mean(rates)

    assert pressure_rate(4.0) > pressure_rate(0.0) + 0.03
