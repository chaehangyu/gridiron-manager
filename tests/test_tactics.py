"""M4: 전술·숙련도·훈련·스카우팅·코디네이터·주간 진행."""
import pytest

from gridiron.engine.adapter import build_team
from gridiron.engine.ai import coordinator as C
from gridiron.engine.norms import compute_norms
from gridiron.engine.outcome.data_model import DataOutcome
from gridiron.engine.skeleton.game import GameSim
from gridiron.engine.skeleton.settings import GameSettings
from gridiron.tactics import familiarity as F
from gridiron.tactics import scouting
from gridiron.tactics.model import Tactics, from_tendencies, preset
from gridiron.tactics.training import TrainingPlan, apply_week


# ── 전술 모델 ─────────────────────────────────────────────────────
def test_tactics_roundtrip_and_gameplan_merge():
    t = preset("west_coast", "tampa2")
    t.situational = {"3l|opp": {"pass": 0.1, "blitz": 1.5}}
    again = Tactics.from_dict(t.to_dict())
    assert again.to_dict() == t.to_dict()
    week = t.merged({"defense": {"blitz": 2.0}})
    assert week.defense.blitz == 2.0 and t.defense.blitz != 2.0   # 원본은 그대로 (F4-7b)
    assert week.offense.run_share == t.offense.run_share


def test_tactics_validation():
    t = Tactics()
    t.offense.run_style = "triple_option"
    t.predictability.lam = 0.9
    t.situational = {"9x|moon": {}}
    errs = t.validate()
    assert len(errs) == 3


def test_run_share_moves_pass_logit():
    t = Tactics()
    assert t.offense.pass_shift() == 0.0
    t.offense.run_share = 0.30
    assert t.offense.pass_shift() > 0
    t.offense.run_share = 0.60
    assert t.offense.pass_shift() < 0


def test_from_tendencies_maps_ratios():
    league = {"offense": {"proe": 0.0, "pa_rate": 0.24, "screen_rate": 0.09, "deep_rate": 0.18, "outside_run": 0.48,
                          "personnel": {"11": 0.6, "12": 0.25}},
              "defense": {"blitz_rate": 0.3, "man_rate": 0.3, "coverage": {"C1": 0.2, "C3": 0.3},
                          "heavy_box": 0.07, "light_box": 0.4}}
    team = {"offense": {**league["offense"], "proe": 0.05, "outside_run": 0.62, "pa_rate": 0.36},
            "defense": {**league["defense"], "blitz_rate": 0.45, "coverage": {"C1": 0.4, "C3": 0.2}}}
    t = from_tendencies(team, league)
    assert t.offense.run_share < 1 - 0.57          # 패스를 더 했다
    assert t.offense.run_style == "outside_zone"
    assert t.offense.play_action == pytest.approx(1.5)
    assert t.defense.blitz > 1.5 and t.defense.coverage["C1"] > 1.5


# ── 숙련도·훈련·스카우팅 ──────────────────────────────────────────
def test_familiarity_rules():
    assert F.multiplier(F.BASE) == pytest.approx(1.0)
    assert F.multiplier(0) == pytest.approx(0.935, abs=1e-3)
    assert F.mistake_factor(90) == 1.0 and F.mistake_factor(40) == pytest.approx(1.6)
    fam = F.default()
    usage = {"run_zone": 30, "run_gap": 2, "pass_quick": 10, "pass_inter": 10, "pass_deep": 5, "pass_screen": 1,
             "pass_total": 26, "pass_pa": 1, "cov_man": 25, "cov_zone": 5, "def_pass_total": 30, "blitz": 9}
    after = F.after_game(fam, usage)
    assert after["run_zone"] == 82 and after["cov_man"] == 82 and after["run_gap"] == 80
    decayed = F.weekly_decay(fam, usage)
    assert decayed["pass_pa"] == 79 and decayed["pass_screen"] == 79 and decayed["run_zone"] == 80


def test_initial_familiarity_from_usage():
    lg = {"offense": {"outside_run": 0.5, "deep_rate": 0.2, "pa_rate": 0.25, "screen_rate": 0.1},
          "defense": {"man_rate": 0.3, "blitz_rate": 0.3}}
    tm = {"offense": {"outside_run": 0.5, "deep_rate": 0.1, "pa_rate": 0.25, "screen_rate": 0.1},
          "defense": {"man_rate": 0.15, "blitz_rate": 0.6}}
    f = F.initial("3-4", tm, lg)
    assert f["front_34"] > f["front_43"]
    assert f["pass_deep"] < 70 < F.BASE <= f["blitz"]
    assert f["cov_man"] < f["cov_zone"]


def test_training_week():
    fam = F.default()
    out, prep, cond = apply_week(TrainingPlan(main="familiarity:cov_man", sub="opponent", intensity="hard"),
                                 fam, ["cov_man"])
    assert out["cov_man"] == pytest.approx(80 + 5 * 1.6)
    assert out["run_zone"] == pytest.approx(80 + 1.5 * 1.6)
    assert prep["kappa_mult"] > 1 and prep["scout_add"] > 0 and cond == -10
    _, prep2, _ = apply_week(TrainingPlan(main="redzone", sub=None, intensity="normal"), fam, [])
    assert prep2["drill"]["redzone"] == pytest.approx(0.06)
    assert TrainingPlan(main="sleep").validate()


def test_scouting_prior_grows_with_games():
    game = {"off": {"plays": 60, "pass": 45, "xpass": 33, "fam": {"deep": 15, "quick": 20}, "pa": 5},
            "def": {"pass_faced": 35, "runs_faced": 25, "cov": {"C1": 20, "C3": 15}, "blitz": 14, "box": {}}}
    rec = None
    for _ in range(4):
        rec = scouting.accumulate(rec, game)
    p0 = scouting.prior(None, None, None)
    p4 = scouting.prior(rec, None, None)
    assert p0["w"] == pytest.approx(0.3) and p4["w"] == pytest.approx(0.8)
    assert p4["proe"] == pytest.approx((180 - 132) / 240 * 4 / 6)
    assert p4["blitz"] == pytest.approx(0.4)


# ── 코디네이터 ────────────────────────────────────────────────────
def test_offense_belief_learns_tendency():
    b = C.OffenseBelief(kappa=20, prior_dev=0.0, prior_fam=None, w_scout=0.3)
    keys = C.OffenseBelief.keys("1", "own", "close", "11")
    assert b.b_pass(keys, 0.55) == pytest.approx(0.55)
    for _ in range(30):
        b.observe(keys, True, 0.55, "deep")
    assert 0.65 < b.b_pass(keys, 0.55) < 1.0
    assert b.exposure() > 40
    fam = b.fam_probs("1", {"screen": 0.1, "quick": 0.4, "inter": 0.3, "deep": 0.2})
    assert fam["deep"] > 0.5


def test_tilt_only_reallocates():
    base = {"a": 0.5, "b": 0.5}
    assert C.tilt(base, {"a": 0.0, "b": 0.0}, 0.35, 0.02) == pytest.approx(base)
    tilted = C.tilt(base, {"a": 0.02, "b": 0.0}, 0.35, 0.02)
    assert tilted["a"] > 0.5 and sum(tilted.values()) == pytest.approx(1.0)


def test_identity_coverage_follows_tactics():
    man = preset("balanced", "man_blitz")
    zone = preset("balanced", "tampa2")
    pm = sum(v for (c, _), v in C.identity_coverage("1st", "11", man, {}).items() if c in ("C0", "C1", "2M"))
    pz = sum(v for (c, _), v in C.identity_coverage("1st", "11", zone, {}).items() if c in ("C0", "C1", "2M"))
    blitz_m = sum(v for (_, b), v in C.identity_coverage("1st", "11", man, {}).items() if b)
    blitz_z = sum(v for (_, b), v in C.identity_coverage("1st", "11", zone, {}).items() if b)
    assert pm > 0.5 > pz and blitz_m > blitz_z


# ── 엔진 통합 ─────────────────────────────────────────────────────
def _game(lg, seed, **kw):
    abbrs = sorted(lg.teams)[:2]
    day = lg.season_start()
    teams = [build_team(lg, abbrs[0], 0, day), build_team(lg, abbrs[1], 1, day)]
    out = DataOutcome.for_league(lg, **kw)
    sim = GameSim(teams, settings=GameSettings.from_config(), outcome=out, seed=seed, norms=compute_norms(lg),
                  do_play_by_play=kw.get("explain", False))
    return sim, out


def test_explain_contributions_sum(sample_league):
    sim, _ = _game(sample_league, 3, explain=True)
    res = sim.run()
    rows = [e for e in res["playByPlay"] if "x_s_total" in e]
    assert rows
    for e in rows:
        s = e["x_s_rating"] + e["x_s_fam"] + e["x_s_anticip"] + e["x_s_drill"] + e["x_s_home"] + e["x_s_situ"]
        assert s == pytest.approx(e["x_s_total"], abs=2e-3)


def test_learning_off_has_no_read_effect(sample_league):
    sim, out = _game(sample_league, 4, learning=False)
    sim.run()
    rep = out.report()
    assert all(r["anticip_plays"] == 0 for r in rep.values())
    assert all(r["usage"] and r["summary"]["off"]["plays"] > 40 for r in rep.values())


def test_low_familiarity_costs(sample_league):
    """숙련도 40 vs 100: 같은 시드 묶음에서 득점이 줄어든다 (T7의 단위 버전)."""
    from statistics import mean
    norms = compute_norms(sample_league)
    abbrs = sorted(sample_league.teams)[:2]
    day = sample_league.season_start()

    def pts(f):
        out = []
        for seed in range(24):
            home, away = build_team(sample_league, abbrs[0], 0, day), build_team(sample_league, abbrs[1], 1, day)
            home.familiarity = {d: f for d in F.DOMAINS}
            res = GameSim([home, away], settings=GameSettings.from_config(), seed=seed, norms=norms,
                          outcome=DataOutcome.for_league(sample_league)).run()
            out.append(res["team"][0].stat["pts"] - res["team"][1].stat["pts"])
        return mean(out)

    assert pts(100) > pts(40)


# ── 저장·주간 진행·CLI ───────────────────────────────────────────
def test_team_state_roundtrip(tmp_path):
    from gridiron.data.sample import generate_sample_league
    from gridiron.db.store import load_league, save_league
    lg = generate_sample_league(seed=3)
    abbr = sorted(lg.teams)[0]
    t = lg.teams[abbr]
    t.tactics = preset("air_raid", "man_blitz")
    t.gameplan, t.gameplan_week = {"defense": {"blitz": 2.2}}, 1
    t.familiarity["cov_man"] = 55.5
    t.training = TrainingPlan(main="familiarity:cov_man", sub=None, intensity="hard")
    path = tmp_path / "s.sqlite"
    save_league(lg, path, user_team=abbr)
    back, _ = load_league(path)
    bt = back.teams[abbr]
    assert bt.tactics.to_dict() == t.tactics.to_dict()
    assert bt.tactics_for_week(1).defense.blitz == 2.2 and bt.tactics_for_week(2).defense.blitz == t.tactics.defense.blitz
    assert bt.familiarity["cov_man"] == 55.5
    assert bt.training.main == "familiarity:cov_man" and bt.training.sub is None


def test_weekly_cycle_and_cli(tmp_path, capsys):
    from pathlib import Path

    from gridiron.cli import main
    from gridiron.db.store import load_league
    path = str(tmp_path / "c.sqlite")
    main(["new-game", "--source", "sample", "--team", "S01", "--save", path])
    main(["tactics", "--save", path, "--preset", "ground_pound+seattle_c3"])
    main(["tactics", "--save", path, "--situ", "3s|opp", "pass=-0.2", "blitz=1.3"])
    main(["train", "--save", path, "--main", "familiarity:auto", "--sub", "redzone", "--intensity", "light"])
    main(["gameplan", "--save", path, "--set", "defense.blitz=1.6"])
    main(["sim-game", "--save", path])
    out = capsys.readouterr().out
    assert "전술 리포트" in out and "노출도" in out
    main(["sim-week", "--save", path])
    lg, _ = load_league(Path(path))
    me = lg.teams["S01"]
    assert me.tactics.offense.run_style == "gap" and "3s|opp" in me.tactics.situational
    assert lg.prepared_week == 1 and me.scouting["games"] == 1
    assert any(t.scouting.get("games") == 1 for a, t in lg.teams.items() if a != "S01")
    main(["gameplan", "--save", path])
    assert "스카우팅 리포트" in capsys.readouterr().out
