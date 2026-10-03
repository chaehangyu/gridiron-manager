"""포지션별 "능력치 ← 지표" 조합표 (PRD §7.2).

값은 (지표, 가중치). 가중치가 음수면 낮을수록 좋은 지표다. 같은 포지션 선수끼리의 표준점수를 가중 합한 뒤
포지션 안 백분위로 1–20을 정한다. `OFFSET`은 그 기술을 주로 쓰지 않는 포지션의 절대 척도 보정이다
(F2-5 원칙 2: 기술 등급의 기준 집단은 그 기술을 주로 쓰는 포지션).
"""
from __future__ import annotations

R = dict  # 가독성용

RUSH = [("rush_prod", 0.6), ("rapm_pressure_def", 0.4)]
RUN_STOP = [("rapm_run_def", -0.4), ("run_stop_tkl", 0.35), ("tfl_rate", 0.25)]
SHED = [("rapm_run_def", -0.3), ("tfl_rate", 0.3), ("rush_prod", 0.25), ("rapm_pressure_def", 0.15)]
TACKLE = [("tackle_rate", 0.5), ("run_stop_tkl", 0.5)]
PURSUIT = [("pursuit_tkl", 1.0)]
MAN = [("rapm_cov_man", -0.55), ("rapm_cov_all", -0.2), ("ball_prod", 0.25)]
ZONE = [("rapm_cov_zone", -0.55), ("rapm_cov_all", -0.2), ("ball_prod", 0.25)]
BALL = [("ball_prod", 0.6), ("int_rate", 0.4)]
CATCH = [("drop_rate", -0.6), ("catch_oe", 0.4)]
RETURN = [("kick_return", 0.5), ("punt_return", 0.5)]

RECIPES: dict[str, dict[str, list[tuple[str, float]]]] = {
    "QB": R(short_accuracy=[("cpoe_short", 1.0)], medium_accuracy=[("cpoe_med", 1.0)],
            deep_accuracy=[("cpoe_deep", 1.0)], decision=[("itw_rate", -0.6), ("qb_epa", 0.4)],
            pocket_presence=[("sack_when_pressured", -0.5), ("qb_fault_sack", -0.5)],
            throw_power=[("max_air", 0.7), ("deep_share", 0.3)],
            throw_on_run=[("cpoe_on_run", 0.7), ("scramble_yds", 0.3)],
            elusiveness=[("scramble_yds", 1.0)], ball_security=[("qb_fumble", -1.0)],
            composure=[("qb_epa_clutch", 1.0)]),
    "RB": R(vision=[("ryoe", 0.5), ("run_success", 0.5)],
            elusiveness=[("explosive_run", 0.5), ("yac_oe", 0.3), ("ryoe", 0.2)],
            break_tackle=[("short_conv", 0.4), ("no_stuff", 0.4), ("ryoe", 0.2)],
            ball_security=[("fumble_rate", -1.0)], catching=CATCH,
            route_running=[("tprr", 0.6), ("yprr", 0.4)], release=[("tprr", 1.0)],
            pass_block=[("rapm_pressure_off", -1.0)], run_block=[("rapm_run_off", 1.0)],
            lead_block=[("rapm_run_off", 1.0)], returning=RETURN),
    "FB": R(lead_block=[("rapm_run_off", 1.0)], run_block=[("rapm_run_off", 1.0)],
            pass_block=[("rapm_pressure_off", -1.0)], catching=CATCH, break_tackle=[("short_conv", 1.0)]),
    "WR": R(route_running=[("tprr", 0.4), ("separation", 0.3), ("yprr", 0.3)],
            release=[("tprr_man", 0.6), ("separation", 0.4)], catching=CATCH,
            contested_catch=[("contested_rate", 0.7), ("catch_oe", 0.3)],
            elusiveness=[("yac_oe", 1.0)], break_tackle=[("yac_oe", 1.0)], vision=[("yac_oe", 0.5), ("yprr", 0.5)],
            ball_security=[("fumble_rate", -1.0)], returning=RETURN),
    "TE": R(route_running=[("tprr", 0.4), ("separation", 0.3), ("yprr", 0.3)],
            release=[("tprr_man", 0.6), ("separation", 0.4)], catching=CATCH,
            contested_catch=[("contested_rate", 0.7), ("catch_oe", 0.3)],
            elusiveness=[("yac_oe", 1.0)], break_tackle=[("yac_oe", 1.0)], ball_security=[("fumble_rate", -1.0)],
            run_block=[("rapm_run_off", 1.0)], pass_block=[("rapm_pressure_off", -1.0)],
            lead_block=[("rapm_run_off", 1.0)]),
    "OL": R(pass_block=[("rapm_pressure_off", -1.0)], run_block=[("rapm_run_off", 1.0)]),
    "EDGE": R(power_rush=RUSH, finesse_rush=RUSH, run_stop=RUN_STOP, block_shedding=SHED, tackling=TACKLE,
              pursuit=PURSUIT, man_coverage=[("rapm_cov_man", -1.0)], zone_coverage=[("rapm_cov_zone", -1.0)]),
    "DT": R(power_rush=RUSH, finesse_rush=RUSH, run_stop=RUN_STOP, block_shedding=SHED, tackling=TACKLE,
            pursuit=PURSUIT),
    "LB": R(tackling=TACKLE, run_stop=RUN_STOP, pursuit=PURSUIT, zone_coverage=ZONE, man_coverage=MAN,
            block_shedding=[("rapm_run_def", -0.5), ("tfl_rate", 0.5)], power_rush=RUSH, finesse_rush=RUSH,
            ball_skills=BALL),
    "CB": R(man_coverage=MAN, zone_coverage=ZONE, ball_skills=BALL, tackling=[("tackle_rate", 0.6), ("run_stop_tkl", 0.4)],
            pursuit=PURSUIT, run_stop=[("rapm_run_def", -0.5), ("run_stop_tkl", 0.5)], press=[("rapm_cov_man", -1.0)],
            returning=RETURN),
    "S": R(man_coverage=MAN, zone_coverage=ZONE, ball_skills=BALL, tackling=[("tackle_rate", 0.6), ("run_stop_tkl", 0.4)],
           pursuit=PURSUIT, run_stop=[("rapm_run_def", -0.5), ("run_stop_tkl", 0.5)], press=[("rapm_cov_man", -1.0)],
           returning=RETURN),
    "K": R(kick_accuracy=[("fg_oe", 0.8), ("xp_rate", 0.2)], kick_power=[("fg_long_oe", 0.5), ("fg_long_share", 0.5)]),
    "P": R(punt_power=[("punt_gross", 1.0)], punt_accuracy=[("punt_pin", 1.0)]),
}
RECIPE_GROUP = {"OT": "OL", "OG": "OL", "C": "OL"}

# 주력이 아닌 기술의 절대 척도 보정 (포지션 내 백분위 결과에 더한다)
OFFSET: dict[str, dict[str, float]] = {
    "QB": {"elusiveness": -4.0, "ball_security": -1.0},
    "RB": {"pass_block": -4.0, "route_running": -3.0, "release": -4.0, "run_block": -5.0, "lead_block": -4.0,
           "catching": -1.5, "returning": -1.0},
    "FB": {"catching": -3.0, "pass_block": -3.0, "break_tackle": -2.0, "run_block": -1.0},
    "WR": {"vision": -2.0, "break_tackle": -2.0, "elusiveness": -0.5, "returning": -1.0},
    "TE": {"route_running": -1.5, "release": -1.5, "catching": -0.5, "elusiveness": -2.0, "break_tackle": -1.0,
           "pass_block": -3.0, "run_block": -1.5, "lead_block": -2.0},
    "EDGE": {"man_coverage": -6.0, "zone_coverage": -5.0, "tackling": -1.0, "pursuit": -1.0},
    "DT": {"finesse_rush": -1.5, "pursuit": -3.0, "tackling": -1.0},
    "LB": {"power_rush": -4.0, "finesse_rush": -4.0, "man_coverage": -2.5, "zone_coverage": -1.0,
           "block_shedding": -1.5, "ball_skills": -2.0},
    "CB": {"tackling": -2.0, "pursuit": -1.0, "run_stop": -4.0, "returning": -1.0},
    "S": {"man_coverage": -1.0, "press": -2.0, "run_stop": -1.5, "returning": -2.0},
}

# 신체 능력치를 섞는 기술 (측정 기술 × (1−w) + 신체 × w)
PHYS_BLEND: dict[str, list[tuple[str, str, float]]] = {
    "EDGE": [("pursuit", "speed", 0.4)], "DT": [("pursuit", "speed", 0.4)], "LB": [("pursuit", "speed", 0.4)],
    "CB": [("pursuit", "speed", 0.4), ("press", "strength", 0.3)],
    "S": [("pursuit", "speed", 0.4), ("press", "strength", 0.3)],
    "RB": [("returning", "speed", 0.4)], "WR": [("returning", "speed", 0.4)],
}
# 패스 러시 스타일: 피네스는 스피드, 파워는 근력 쪽으로 기운다 (기록만으로는 둘을 나눌 수 없다)
RUSH_TILT = 0.35
