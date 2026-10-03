"""`data/real/<season>/` CSV → League (실제 NFL 리그).

능력치: `ratings.csv`(M3 실측 파이프라인 결과)가 있으면 그것을 쓰고 `ratings_overrides.csv`(수동 보정)를 덮는다.
없거나 목록에 없는 선수는 `ratings.provisional`의 임시 값을 쓴다 (ratings_source="provisional").
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from ..config import DATA_DIR
from ..domain.attributes import ATTR_KEYS, clamp
from ..domain.depth import auto_depth_chart
from ..domain.models import League, Player, RosterStatus, ScheduledGame, Team
from ..domain.positions import Front, Position
from ..ratings.provisional import generate_attributes, provisional_quality


def _int(v: str) -> int | None:
    if v in ("", None, "None", "NA"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _date(v: str) -> date | None:
    return date.fromisoformat(v[:10]) if v else None


def load_ratings(base: Path) -> dict[str, tuple[str, dict[str, float]]]:
    """gsis_id → (basis, 능력치). 수동 보정 CSV(gsis_id, attribute, value)를 마지막에 덮는다."""
    path = base / "ratings.csv"
    if not path.exists():
        return {}
    out: dict[str, tuple[str, dict[str, float]]] = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["gsis_id"]] = (r["basis"], {k: float(r[k]) for k in ATTR_KEYS})
    ov = base / "ratings_overrides.csv"
    if ov.exists():
        with ov.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["gsis_id"] in out and r["attribute"] in ATTR_KEYS and r["value"]:
                    out[r["gsis_id"]][1][r["attribute"]] = clamp(float(r["value"]))
    return out


def load_real_league(season: int = 2026, data_dir: Path | None = None) -> League:
    base = data_dir or DATA_DIR / "real" / str(season)
    if not (base / "players.csv").exists():
        raise FileNotFoundError(f"{base}에 실데이터가 없습니다. `gridiron fetch-data --season {season}`를 먼저 실행하세요.")

    teams: dict[str, Team] = {}
    with (base / "teams.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            teams[r["abbr"]] = Team(abbr=r["abbr"], city=r["city"], nickname=r["nickname"], conference=r["conference"],
                                    division=r["division"], color=r["color"], color2=r["color2"],
                                    front=Front(r["front"]))

    measured = load_ratings(base)
    players: dict[str, Player] = {}
    with (base / "players.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            status = RosterStatus(r["roster_status"])
            pos = Position(r["position"])
            exp = _int(r["years_exp"]) or 0
            height, weight = _int(r["height_in"]), _int(r["weight_lb"])
            if r["gsis_id"] in measured:
                source, attributes = measured[r["gsis_id"]]
                source = f"measured:{source}"
            else:
                q = provisional_quality(r["gsis_id"], _int(r["depth_rank"]), _int(r["draft_round"]), exp,
                                        on_practice_squad=status == RosterStatus.PRACTICE_SQUAD,
                                        free_agent=status == RosterStatus.FREE_AGENT)
                attributes = generate_attributes(r["gsis_id"], pos, q, years_exp=exp, height_in=height, weight_lb=weight)
                source = "provisional"
            players[r["gsis_id"]] = Player(
                id=r["gsis_id"], name=r["name"], position=pos, attributes=attributes,
                birth_date=_date(r["birth_date"]), height_in=height, weight_lb=weight, college=r["college"] or None,
                jersey=_int(r["jersey"]), years_exp=exp, draft_year=_int(r["draft_year"]),
                draft_round=_int(r["draft_round"]), draft_pick=_int(r["draft_pick"]), draft_team=r["draft_team"] or None,
                team=r["team"] or None, roster_status=status, ratings_source=source,
            )

    # 실제 뎁스차트 (53인 로스터에 있는 선수만)
    with (base / "depth_chart.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            p = players.get(r["gsis_id"])
            team = teams.get(r["team"])
            if team is None or p is None or p.team != team.abbr or p.roster_status != RosterStatus.ACTIVE:
                continue
            team.depth_chart.setdefault(r["slot"], []).append(r["gsis_id"])

    # 빈 슬롯·부족한 백업은 자동 뎁스차트로 채운다
    for team in teams.values():
        roster = [p for p in players.values() if p.team == team.abbr]
        team.depth_chart = auto_depth_chart(team, roster, keep_existing=True)

    schedule: list[ScheduledGame] = []
    with (base / "schedule.csv").open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            schedule.append(ScheduledGame(
                game_id=r["game_id"], season=int(r["season"]), week=int(r["week"]), game_type=r["game_type"],
                home=r["home"], away=r["away"], gameday=_date(r["gameday"]), stadium=r["stadium"] or None,
                roof=r["roof"] or None, surface=r["surface"] or None, neutral_site=r["neutral_site"] == "1",
            ))

    return League(season=season, teams=teams, players=players, schedule=schedule, source="nflverse")
