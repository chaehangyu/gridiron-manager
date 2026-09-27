"""nflverse 실데이터 수집·가공 (PRD §7.1, M0).

2026 시즌 개막(1주차) 기준으로 팀, 로스터, 뎁스차트, 일정을 받아 우리 포지션·슬롯 체계로 바꾼 뒤
`data/real/<season>/`에 CSV로 저장한다. 결과 파일은 저장소에 커밋한다 (§7.4).

필요 패키지: `pip install -e ".[data]"` (nflreadpy, polars)
"""
from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

from ..config import DATA_DIR

# nflverse 로스터 상태 → 우리 로스터 상태
STATUS_MAP = {"ACT": "active", "INA": "active", "DEV": "practice_squad", "RES": "ir", "CUT": "fa"}

# 뎁스차트 수비 슬롯 이름 변환 (nflverse pos_abb → 우리 슬롯)
DEF_SLOT_34 = {"LDE": "LDE", "NT": "NT", "RDE": "RDE", "WLB": "WOLB", "LILB": "LILB", "RILB": "RILB",
               "SLB": "SOLB", "LCB": "LCB", "RCB": "RCB", "NB": "NB", "FS": "FS", "SS": "SS"}
DEF_SLOT_43 = {"LDE": "LDE", "LDT": "LDT", "RDT": "RDT", "RDE": "RDE", "WLB": "WLB", "MLB": "MLB", "SLB": "SLB",
               "LCB": "LCB", "RCB": "RCB", "NB": "NB", "FS": "FS", "SS": "SS"}
OFF_SLOT = {"QB": "QB", "RB": "RB", "FB": "FB", "TE": "TE", "LT": "LT", "LG": "LG", "C": "C", "RG": "RG", "RT": "RT"}
ST_SLOT = {"PK": "K", "K": "K", "P": "P", "LS": "LS", "H": "H", "KR": "KR", "PR": "PR"}

# 뎁스차트 슬롯이 알려주는 주 포지션 (같은 포지션 그룹 안에서만 덮어쓴다)
SLOT_TO_POSITION_43 = {"LDE": "EDGE", "RDE": "EDGE", "LDT": "DT", "RDT": "DT", "WLB": "LB", "MLB": "LB", "SLB": "LB",
                       "LCB": "CB", "RCB": "CB", "NB": "CB", "FS": "S", "SS": "S"}
SLOT_TO_POSITION_34 = {"LDE": "DT", "RDE": "DT", "NT": "DT", "WOLB": "EDGE", "SOLB": "EDGE", "LILB": "LB",
                       "RILB": "LB", "LCB": "CB", "RCB": "CB", "NB": "CB", "FS": "S", "SS": "S"}
SLOT_TO_POSITION_OFF = {"LT": "OT", "RT": "OT", "LG": "OG", "RG": "OG", "C": "C"}


def base_position(depth_pos: str | None, group: str | None, weight: float | None, front: str) -> str | None:
    """nflverse depth_chart_position → 우리 주 포지션 (뎁스차트 슬롯 정보가 없을 때의 기본값)."""
    p = (depth_pos or group or "").upper()
    direct = {"QB": "QB", "RB": "RB", "FB": "FB", "WR": "WR", "TE": "TE", "K": "K", "P": "P", "LS": "LS",
              "T": "OT", "OT": "OT", "G": "OG", "OG": "OG", "C": "C", "DT": "DT", "NT": "DT",
              "ILB": "LB", "MLB": "LB", "LB": "LB", "CB": "CB", "FS": "S", "SS": "S", "S": "S", "DB": "CB",
              "OL": "OG", "DL": "DT"}
    if p == "DE":
        return "DT" if front == "3-4" else "EDGE"
    if p == "OLB":
        if front == "3-4" or (weight is not None and weight >= 250):
            return "EDGE"
        return "LB"
    return direct.get(p)


def draft_round_from_pick(pick: int | None) -> int | None:
    if pick is None or (isinstance(pick, float) and math.isnan(pick)):
        return None
    return min(7, max(1, math.ceil(pick / 32)))


def fetch(season: int = 2026, out_dir: Path | None = None, roster_week: int = 1) -> Path:
    import nflreadpy as nfl
    import polars as pl

    out = out_dir or DATA_DIR / "real" / str(season)
    out.mkdir(parents=True, exist_ok=True)

    # ── 일정 ──
    sched = nfl.load_schedules(season)
    reg_first_day = sched.filter(pl.col("game_type") == "REG")["gameday"].min()
    team_abbrs = sorted(set(sched["home_team"].to_list()) | set(sched["away_team"].to_list()))
    with (out / "schedule.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["game_id", "season", "week", "game_type", "gameday", "home", "away", "stadium", "roof",
                    "surface", "neutral_site", "spread_line", "home_score", "away_score"])
        for r in sched.sort(["week", "gameday", "game_id"]).iter_rows(named=True):
            w.writerow([r["game_id"], r["season"], r["week"], r["game_type"], r["gameday"], r["home_team"],
                        r["away_team"], r["stadium"], r["roof"], r["surface"],
                        int(r["location"] == "Neutral"), r["spread_line"], r["home_score"], r["away_score"]])

    # ── 뎁스차트 (1주차 첫 경기 전날 이전 마지막 스냅샷) ──
    dc_all = nfl.load_depth_charts(season)
    cutoff = str(reg_first_day)
    snap_day = max(d for d in dc_all["dt"].str.slice(0, 10).unique().to_list() if d < cutoff)
    dc = dc_all.filter(pl.col("dt").str.slice(0, 10) == snap_day)
    fronts = {}
    for team, grp in dc.select(["team", "pos_grp"]).unique().iter_rows():
        if grp.startswith("Base 3-4"):
            fronts[team] = "3-4"
        elif grp.startswith("Base 4-3"):
            fronts.setdefault(team, "4-3")

    depth_rows = []
    for (team,), sub in dc.group_by(["team"]):
        front = fronts.get(team, "4-3")
        def_map = DEF_SLOT_34 if front == "3-4" else DEF_SLOT_43
        # WR 슬롯: pos_slot 순서대로 X, Z, SLOT
        wr = sub.filter(pl.col("pos_abb") == "WR")
        wr_slots = sorted(wr["pos_slot"].unique().to_list())
        wr_names = {s: n for s, n in zip(wr_slots, ["WR_X", "WR_Z", "WR_SLOT"])}
        for r in sub.sort(["pos_slot", "pos_rank"]).iter_rows(named=True):
            abb, grp = r["pos_abb"], r["pos_grp"]
            if grp == "Special Teams":
                slot = ST_SLOT.get(abb)
            elif grp.startswith("Base"):
                slot = def_map.get(abb)
            elif abb == "WR":
                slot = wr_names.get(r["pos_slot"])
            else:
                slot = OFF_SLOT.get(abb)
            if slot is None or r["gsis_id"] is None:
                continue
            depth_rows.append({"team": team, "slot": slot, "rank": r["pos_rank"], "gsis_id": r["gsis_id"],
                               "player_name": r["player_name"]})
    # 슬롯 안 순번을 1부터 다시 매긴다 (WR은 전체 순위가 섞여 있음)
    depth_rows.sort(key=lambda x: (x["team"], x["slot"], x["rank"]))
    ranks: dict[tuple[str, str], int] = {}
    seen: set[tuple[str, str, str]] = set()
    cleaned = []
    for row in depth_rows:
        key = (row["team"], row["slot"], row["gsis_id"])
        if key in seen:
            continue
        seen.add(key)
        ranks[(row["team"], row["slot"])] = ranks.get((row["team"], row["slot"]), 0) + 1
        cleaned.append({**row, "rank": ranks[(row["team"], row["slot"])]})
    with (out / "depth_chart.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["team", "slot", "rank", "gsis_id", "player_name"])
        w.writeheader()
        w.writerows(cleaned)

    # ── 팀 ──
    teams = nfl.load_teams().filter(pl.col("team_abbr").is_in(team_abbrs))
    with (out / "teams.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["abbr", "city", "nickname", "conference", "division", "color", "color2", "front"])
        for r in teams.sort("team_abbr").iter_rows(named=True):
            city = r["team_name"][: -len(r["team_nick"])].strip()
            w.writerow([r["team_abbr"], city, r["team_nick"], r["team_conf"], r["team_division"].split()[-1],
                        r["team_color"], r["team_color2"], fronts.get(r["team_abbr"], "4-3")])

    # ── 로스터 (1주차) + 선수 정보 ──
    rw = nfl.load_rosters_weekly(season).filter(pl.col("week") == roster_week)
    bio = nfl.load_players().select(["gsis_id", "birth_date", "draft_round", "draft_pick", "draft_year", "draft_team",
                                     "college_name"])
    rw = rw.join(bio, on="gsis_id", how="left", suffix="_p")
    slot_pos: dict[str, str] = {}
    best_rank: dict[str, int] = {}
    for row in cleaned:
        front = fronts.get(row["team"], "4-3")
        m = SLOT_TO_POSITION_34 if front == "3-4" else SLOT_TO_POSITION_43
        pos = m.get(row["slot"]) or SLOT_TO_POSITION_OFF.get(row["slot"])
        if pos and row["gsis_id"] not in slot_pos:
            slot_pos[row["gsis_id"]] = pos
        if row["slot"] not in ("KR", "PR", "H"):
            best_rank[row["gsis_id"]] = min(best_rank.get(row["gsis_id"], 99), row["rank"])

    compatible = {"OL": {"OT", "OG", "C"}, "DL": {"EDGE", "DT"}, "LB": {"EDGE", "LB"}, "DB": {"CB", "S"}}
    fields = ["gsis_id", "name", "team", "position", "roster_status", "nfl_status", "jersey", "birth_date",
              "height_in", "weight_lb", "college", "years_exp", "draft_year", "draft_round", "draft_pick",
              "draft_team", "depth_rank"]
    rows = []
    for r in rw.iter_rows(named=True):
        status = STATUS_MAP.get(r["status"])
        if status is None or r["gsis_id"] is None:
            continue
        front = fronts.get(r["team"], "4-3")
        pos = base_position(r["depth_chart_position"], r["position"], r["weight"], front)
        override = slot_pos.get(r["gsis_id"])
        if override and override in compatible.get(r["position"], {override}):
            pos = override
        if pos is None:
            continue
        draft_round = r["draft_round"] if r["draft_round"] is not None else draft_round_from_pick(r["draft_number"])
        rows.append({
            "gsis_id": r["gsis_id"], "name": r["full_name"], "team": r["team"] if status != "fa" else "",
            "position": pos, "roster_status": status, "nfl_status": r["status"], "jersey": r["jersey_number"],
            "birth_date": r["birth_date"] or "", "height_in": r["height"], "weight_lb": r["weight"],
            "college": r["college"] or r.get("college_name") or "", "years_exp": r["years_exp"],
            "draft_year": r["draft_year"] if r["draft_year"] is not None else r["entry_year"],
            "draft_round": draft_round,
            "draft_pick": r["draft_pick"] if r["draft_pick"] is not None else r["draft_number"],
            "draft_team": r["draft_team"] or r["draft_club"] or "", "depth_rank": best_rank.get(r["gsis_id"], ""),
        })
    rows.sort(key=lambda x: (x["team"], x["position"], x["name"]))
    with (out / "players.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    meta = {"season": season, "roster_week": roster_week, "depth_chart_snapshot": snap_day,
            "first_game_day": str(reg_first_day), "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "nflverse via nflreadpy", "counts": {"players": len(rows), "depth_rows": len(cleaned),
                                                          "games": sched.height, "teams": teams.height}}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_dates(meta_path: Path) -> date:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return date.fromisoformat(meta["first_game_day"])
