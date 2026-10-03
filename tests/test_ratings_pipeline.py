"""M3: 실측 능력치 파이프라인과 로딩."""
import csv
import json
import shutil
from pathlib import Path

import pytest

from gridiron.config import DATA_DIR
from gridiron.data.real_league import load_real_league
from gridiron.ratings.position_rating import position_rating

np = pytest.importorskip("numpy")
pytest.importorskip("pandas")

from gridiron.ratings.derive import build as B  # noqa: E402
from gridiron.ratings.derive import physical  # noqa: E402

REAL = DATA_DIR / "real" / "2026"


def test_percentile_to_rating_follows_grade_table():
    p = np.array([0.0, 0.10, 0.50, 0.75, 0.90, 0.97, 1.0])
    r = B.p2r(p)
    assert list(r) == sorted(r)
    assert r[1] == pytest.approx(7.0) and r[3] == pytest.approx(14.3) and r[-1] == pytest.approx(20.0)


def test_weighted_percentile_uses_snap_weights():
    ref = np.array([1.0, 2.0, 3.0])
    # 많이 뛴 선수(가중치 큼)가 분포를 정한다
    assert B.wpct(np.array([2.0]), ref, np.array([1.0, 1.0, 98.0]))[0] < 0.05
    assert B.wpct(np.array([2.0]), ref, np.array([1.0, 1.0, 1.0]))[0] == pytest.approx(0.5)


def test_shrink_pulls_small_samples_to_prior():
    rng = np.random.default_rng(0)
    n = np.array([400.0] * 30 + [5.0, 0.0])
    true = rng.normal(0, 0.05, 32)
    mean = true + rng.normal(0, 0.3, 32) / np.sqrt(np.maximum(n, 1))
    mean[-2] = 0.9  # 표본 5개짜리 극단값
    X = np.ones((32, 1))
    th, k = B.shrink(mean, n, np.full(32, 0.09), X)
    assert k > 5
    assert abs(th[-2]) < 0.5 * 0.9          # 작은 표본의 극단값은 크게 당겨진다
    assert abs(th[0] - mean[0]) < 0.05       # 큰 표본은 거의 그대로
    assert th[-1] == pytest.approx(th[:30].mean(), abs=0.05)  # 기록 없는 선수 = 사전값


def test_physical_anchors():
    r = physical.to_rating("forty", np.array([4.28, 4.62, 5.40, 4.20]))
    assert list(r) == pytest.approx([20.0, 12.0, 1.0, 20.0])
    assert physical.to_rating("bench", np.array([23.0]))[0] == pytest.approx(12.0)
    assert physical.from_rating("vertical", 16) == pytest.approx(37.0)


def test_committed_ratings_pass_distribution_rules():
    report = json.loads((REAL / "ratings_report.json").read_text(encoding="utf-8"))
    v = report["validation"]
    assert v["pass"]
    assert all(12.5 <= m <= 13.5 for pos, m in v["starter_pr_mean"].items() if pos != "LS")
    assert all(c <= 3 for c in v["twenty_counts"].values())


def test_real_league_uses_measured_ratings():
    lg = load_real_league(2026)
    sources = {p.ratings_source for p in lg.players.values()}
    assert sources <= {"measured:measured", "measured:prior"}
    qbs = sorted((p for p in lg.players.values() if p.position.value == "QB" and p.team),
                 key=position_rating, reverse=True)
    # 주전 QB가 백업 QB보다 높게 평가된다 (팀이 정한 뎁스 순번과 실측 기록이 함께 반영)
    starters = {pid for t in lg.teams.values() for pid in t.depth_chart.get("QB", [])[:1]}
    top32 = {p.id for p in qbs[:32]}
    assert len(top32 & starters) >= 22


def test_overrides_are_applied(tmp_path: Path):
    for f in REAL.iterdir():
        shutil.copy(f, tmp_path / f.name)
    with (REAL / "ratings.csv").open(encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))
    (tmp_path / "ratings_overrides.csv").write_text(
        f"gsis_id,attribute,value,note\n{row['gsis_id']},speed,19.5,test\n{row['gsis_id']},catching,25,clamped\n",
        encoding="utf-8")
    lg = load_real_league(2026, data_dir=tmp_path)
    p = lg.players[row["gsis_id"]]
    assert p.attributes["speed"] == 19.5
    assert p.attributes["catching"] == 20.0


def test_2025_reproduction_meets_m3_criteria():
    """tools/reproduce_season.py 결과 (2022–2024 기록 능력치로 2025 정규시즌 재현, PRD M3 완료 기준)."""
    rep = json.loads((DATA_DIR / "real" / "2025" / "reproduction.json").read_text(encoding="utf-8"))
    r = rep["results"]["1.25"]
    assert r["rho_point_diff"] >= 0.4
    assert 0.8 <= r["sd_ratio"] <= 1.25
    assert abs(r["league_ppg_sim"] - r["league_ppg_real"]) <= 2.0
    assert r["brier_power"] < 0.25
