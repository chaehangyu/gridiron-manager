"""도메인 모델·샘플 리그·실데이터 로더·세이브 테스트."""
from pathlib import Path

import pytest

from gridiron.config import DATA_DIR
from gridiron.domain.attributes import ATTR_KEYS, grade_label, stars
from gridiron.domain.models import RosterStatus
from gridiron.domain.positions import SLOT_POSITIONS, all_slots
from gridiron.ratings.position_rating import position_rating


def test_grade_and_star_scales():
    assert grade_label(20) == "역대급"
    assert grade_label(12.4) == "평균 주전"
    assert grade_label(1) == "사실상 없음"
    assert stars(17.2) == 5.0
    assert stars(13.0) == 3.5
    assert stars(5.0) == 1.0


def test_sample_league_shape(sample_league):
    assert len(sample_league.teams) == 32
    for t in sample_league.teams.values():
        active = sample_league.roster(t.abbr)
        assert len(active) == 53
        assert len(sample_league.roster(t.abbr, (RosterStatus.PRACTICE_SQUAD,))) == 16
        for slot in all_slots(t.front):
            assert t.depth_chart.get(slot), f"{t.abbr} {slot} 비어 있음"
    assert len(sample_league.schedule) == 17 * 16


def test_sample_starters_average_pr_in_target_band(sample_league):
    """F2-5d: 포지션별 주전 PR 평균 12.5–13.5 부근."""
    prs = []
    for t in sample_league.teams.values():
        for slot, ids in t.depth_chart.items():
            if slot in ("KR", "PR", "H") or not ids:
                continue
            p = sample_league.players[ids[0]]
            if p.position in SLOT_POSITIONS[slot]:
                prs.append(position_rating(p))
    mean = sum(prs) / len(prs)
    assert 12.0 <= mean <= 13.8


def test_attributes_complete_and_bounded(sample_league):
    for p in list(sample_league.players.values())[:200]:
        assert set(p.attributes) == set(ATTR_KEYS)
        assert all(1.0 <= v <= 20.0 for v in p.attributes.values())


REAL = DATA_DIR / "real" / "2026" / "players.csv"


@pytest.mark.skipif(not REAL.exists(), reason="실데이터 없음 (gridiron fetch-data)")
def test_real_league_loads():
    from gridiron.data.real_league import load_real_league
    league = load_real_league(2026)
    assert len(league.teams) == 32
    assert len([g for g in league.schedule if g.game_type == "REG"]) == 272
    kc = league.teams["KC"]
    assert league.players[kc.depth_chart["QB"][0]].name == "Patrick Mahomes"
    for t in league.teams.values():
        assert 50 <= len(league.roster(t.abbr)) <= 57
        assert t.depth_chart["QB"] and t.depth_chart["K"]


def test_save_and_load_roundtrip(sample_league, tmp_path: Path):
    from gridiron.db.store import load_league, save_league
    path = tmp_path / "slot.sqlite"
    save_league(sample_league, path, user_team="S01")
    loaded, user = load_league(path)
    assert user == "S01"
    assert set(loaded.teams) == set(sample_league.teams)
    pid = next(iter(sample_league.players))
    a, b = sample_league.players[pid], loaded.players[pid]
    assert a.name == b.name and a.position == b.position and a.roster_status == b.roster_status
    assert all(abs(a.attributes[k] - b.attributes[k]) < 1e-3 for k in ATTR_KEYS)
    t = sample_league.teams["S01"]
    assert loaded.teams["S01"].depth_chart["QB"] == t.depth_chart["QB"]
    assert len(loaded.schedule) == len(sample_league.schedule)


def test_cli_sample_flow(tmp_path: Path, capsys):
    from gridiron.cli import main
    from gridiron.db.store import load_league, standings
    save = str(tmp_path / "c.sqlite")
    main(["new-game", "--source", "sample", "--team", "S01", "--save", save])
    main(["sim-game", "--save", save, "--pbp"])
    main(["sim-week", "--save", save])
    out = capsys.readouterr().out
    assert "경기 종료" in out and "1주차" in out
    league, _ = load_league(Path(save))
    assert league.week == 2
    assert all(g.played for g in league.games_in_week(1))
    rows = standings(Path(save), league.season)
    assert sum(r.wins + r.losses + r.ties for r in rows) == 32
