"""플레이 단위 원천 테이블: pbp + 참여(participation) + FTN 차팅을 한 표로 합친다.

시즌 가중치 `w`를 플레이마다 붙여, 이후 모든 집계가 "최근 시즌일수록 크게" 반영되게 한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ...baseline.build import fetch

# 대상 시즌 직전 시즌부터 거꾸로: 1.0, 0.7, 0.45
SEASON_WEIGHTS = (1.0, 0.7, 0.45)

PBP_COLS = [
    "game_id", "play_id", "season", "season_type", "week", "posteam", "defteam", "play_type", "down", "ydstogo",
    "yardline_100", "qtr", "game_seconds_remaining", "score_differential", "wp", "epa", "qb_epa", "success",
    "yards_gained", "qb_dropback", "qb_scramble", "qb_kneel", "qb_spike", "pass_attempt", "rush_attempt", "sack",
    "complete_pass", "interception", "air_yards", "yards_after_catch", "xyac_mean_yardage", "cp", "cpoe",
    "first_down", "touchdown", "two_point_attempt", "aborted_play", "penalty", "fumble", "fumble_lost",
    "passer_player_id", "receiver_player_id", "rusher_player_id", "fumbled_1_player_id",
    "sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id", "qb_hit_1_player_id", "qb_hit_2_player_id",
    "tackle_for_loss_1_player_id", "tackle_for_loss_2_player_id", "solo_tackle_1_player_id", "solo_tackle_2_player_id",
    "assist_tackle_1_player_id", "assist_tackle_2_player_id", "tackle_with_assist_1_player_id",
    "tackle_with_assist_2_player_id", "pass_defense_1_player_id", "pass_defense_2_player_id", "interception_player_id",
    "forced_fumble_player_1_player_id", "kicker_player_id", "punter_player_id", "kick_distance", "field_goal_result",
    "extra_point_result", "punt_inside_twenty", "touchback", "return_yards", "kickoff_returner_player_id",
    "punt_returner_player_id", "punt_blocked",
]
PART_COLS = ["nflverse_game_id", "play_id", "offense_players", "defense_players", "was_pressure",
             "defense_man_zone_type", "number_of_pass_rushers", "defenders_in_box"]
FTN_COLS = ["nflverse_game_id", "nflverse_play_id", "is_qb_out_of_pocket", "is_interception_worthy", "is_catchable_ball",
            "is_contested_ball", "is_drop", "is_qb_fault_sack", "is_throw_away"]


def window(target: int) -> dict[int, float]:
    """대상 시즌의 기록 창: {시즌: 가중치}."""
    return {target - 1 - i: w for i, w in enumerate(SEASON_WEIGHTS)}


def load_plays(cache: Path, seasons: dict[int, float]) -> pd.DataFrame:
    frames = []
    for y, w in seasons.items():
        pbp = pd.read_parquet(fetch(cache, f"pbp/play_by_play_{y}.parquet"), columns=PBP_COLS)
        pbp = pbp[pbp.season_type == "REG"]
        try:
            part = pd.read_parquet(fetch(cache, f"pbp_participation/pbp_participation_{y}.parquet"), columns=PART_COLS)
            pbp = pbp.merge(part.rename(columns={"nflverse_game_id": "game_id"}), on=["game_id", "play_id"], how="left")
        except Exception:  # noqa: BLE001 - 시즌에 참여 데이터가 없으면 해당 지표만 빠진다
            for c in PART_COLS[2:]:
                pbp[c] = np.nan
        try:
            ftn = pd.read_parquet(fetch(cache, f"ftn_charting/ftn_charting_{y}.parquet"), columns=FTN_COLS)
            ftn = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
            pbp = pbp.merge(ftn, on=["game_id", "play_id"], how="left")
        except Exception:  # noqa: BLE001
            for c in FTN_COLS[2:]:
                pbp[c] = np.nan
        pbp["w"] = w
        frames.append(pbp)
    d = pd.concat(frames, ignore_index=True)
    d["key"] = np.arange(len(d))
    # 플레이 구분
    normal = (d.two_point_attempt != 1) & (d.aborted_play != 1) & (d.qb_kneel != 1) & (d.qb_spike != 1)
    d["is_db"] = normal & (d.qb_dropback == 1) & d.play_type.isin(["pass", "run", "no_play"]) & (d.penalty != 1)
    d["is_run"] = normal & (d.rush_attempt == 1) & (d.qb_scramble != 1) & (d.penalty != 1)
    d["is_att"] = d.is_db & (d.pass_attempt == 1) & (d.sack != 1)
    d["db_qb"] = np.where(d.is_db, d.passer_player_id.fillna(d.rusher_player_id), None)
    d["epa_c"] = d.epa.clip(-4, 4)
    cov = d.defense_man_zone_type.fillna("")
    d["cov"] = np.where(cov == "MAN_COVERAGE", "man", np.where(cov == "ZONE_COVERAGE", "zone", ""))
    return d


def on_field(d: pd.DataFrame) -> pd.DataFrame:
    """스크리미지 플레이별 필드 위 선수 (긴 표): key, gsis_id, side, w, is_db, is_run, cov."""
    base = d.loc[(d.is_db | d.is_run) & d.offense_players.notna(), ["key", "w", "is_db", "is_run", "cov",
                                                                       "offense_players", "defense_players"]]
    out = []
    for side, col in (("off", "offense_players"), ("def", "defense_players")):
        s = base[["key", "w", "is_db", "is_run", "cov", col]].copy()
        s["gsis_id"] = s[col].str.split(";")
        s = s.drop(columns=[col]).explode("gsis_id")
        s = s[s.gsis_id.notna() & (s.gsis_id != "")]
        s["side"] = side
        out.append(s)
    return pd.concat(out, ignore_index=True)
