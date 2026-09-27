"""도메인 모델 → 엔진 골격 입력 변환.

우리 능력치(1–20)를 Football GM 능력치 키(0–100)로 옮긴 뒤, 원본의 합성 능력(COMPOSITE_WEIGHTS)과
포지션별 종합(ovr.football)을 계산한다. 임시 결과 모델(FbgmOutcome)이 이 값을 쓴다.
M2 이후 실데이터 결과 모델은 `PlayerGameSim.attributes`(원래 1–20 능력치)를 직접 쓴다.
"""
from __future__ import annotations

from datetime import date

from ..domain.attributes import to_hundred
from ..domain.depth import engine_depth
from ..domain.models import League, Player, RosterStatus, Team
from .skeleton.types import PlayerGameSim, TeamGameSim


def _mix(a: dict[str, float], parts: list[tuple[str, float]]) -> float:
    total = sum(w for _, w in parts)
    return sum(a[k] * w for k, w in parts) / total


def fbgm_ratings(p: Player) -> dict[str, float]:
    a = p.attributes
    h = p.height_in if p.height_in is not None else 74
    return {
        "hgt": max(0.0, min(100.0, 100 * (h - 64) / (82 - 64))),
        "stre": to_hundred(a["strength"]),
        "spd": to_hundred(_mix(a, [("speed", 0.7), ("acceleration", 0.3)])),
        "endu": to_hundred(a["stamina"]),
        "thv": to_hundred(_mix(a, [("decision", 0.45), ("pocket_presence", 0.3), ("football_iq", 0.25)])),
        "thp": to_hundred(a["throw_power"]),
        "tha": to_hundred(_mix(a, [("short_accuracy", 0.4), ("medium_accuracy", 0.35), ("deep_accuracy", 0.25)])),
        "bsc": to_hundred(a["ball_security"]),
        "elu": to_hundred(_mix(a, [("elusiveness", 0.5), ("agility", 0.25), ("vision", 0.25)])),
        "rtr": to_hundred(_mix(a, [("route_running", 0.7), ("release", 0.3)])),
        "hnd": to_hundred(_mix(a, [("catching", 0.75), ("contested_catch", 0.25)])),
        "rbk": to_hundred(max(a["run_block"], 0.9 * a["lead_block"])),
        "pbk": to_hundred(a["pass_block"]),
        "pcv": to_hundred(_mix(a, [("man_coverage", 0.4), ("zone_coverage", 0.4), ("ball_skills", 0.2)])),
        "tck": to_hundred(_mix(a, [("tackling", 0.7), ("pursuit", 0.3)])),
        "prs": to_hundred(0.5 * max(a["power_rush"], a["finesse_rush"]) + 0.25 * a["power_rush"] + 0.25 * a["finesse_rush"]),
        "rns": to_hundred(_mix(a, [("run_stop", 0.6), ("block_shedding", 0.4)])),
        "kpw": to_hundred(a["kick_power"]),
        "kac": to_hundred(a["kick_accuracy"]),
        "ppw": to_hundred(a["punt_power"]),
        "pac": to_hundred(a["punt_accuracy"]),
    }


# 원본 COMPOSITE_WEIGHTS (constants.football.ts)
COMPOSITE_WEIGHTS: dict[str, tuple[list, list[float]]] = {
    "passingAccuracy": (["tha", "hgt"], [1, 0.2]),
    "passingDeep": (["thp", "tha", "hgt"], [1, 0.1, 0.2]),
    "passingVision": (["thv", "hgt"], [1, 0.5]),
    "athleticism": (["stre", "spd", "hgt"], [1, 1, 0.2]),
    "rushing": (["stre", "spd", "elu"], [0.5, 1, 1]),
    "catching": (["hgt", "hnd"], [0.2, 1]),
    "gettingOpen": (["hgt", "spd", "rtr", "hnd"], [1, 0.25, 2, 1]),
    "speed": (["spd"], [1]),
    "passBlocking": (["hgt", "stre", "spd", "pbk"], [0.5, 1, 0.2, 1]),
    "runBlocking": (["hgt", "stre", "spd", "rbk"], [0.5, 1, 0.4, 1]),
    "passRushing": (["hgt", "stre", "spd", "prs", "tck"], [1, 1, 0.5, 1, 0.25]),
    "runStopping": (["hgt", "stre", "spd", "rns", "tck"], [0.5, 1, 0.5, 1, 0.4]),
    "passCoverage": (["hgt", "spd", "pcv"], [0.1, 1, 1]),
    "tackling": (["spd", "stre", "tck"], [1, 1, 2.5]),
    "avoidingSacks": (["thv", "elu", "stre"], [1, 1, 0.25]),
    "ballSecurity": (["bsc", "stre"], [1, 0.2]),
    "endurance": ([50, "endu"], [1, 1]),
    "kickingPower": (["kpw"], [1]),
    "kickingAccuracy": (["kac"], [1]),
    "puntingPower": (["ppw"], [1]),
    "puntingAccuracy": (["pac"], [1]),
}

# 원본 ovr.football.ts info (계수, 지수)
OVR_INFO: dict[str, dict[str, float]] = {
    "QB": {"passingAccuracy": 3, "passingDeep": 3, "passingVision": 3, "athleticism": 1, "rushing": 1,
           "avoidingSacks": 1, "ballSecurity": 1, "constant0": -1.25},
    "RB": {"rushing": 10, "catching": 2, "gettingOpen": 1, "passBlocking": 1, "runBlocking": 1, "ballSecurity": 1,
           "constant0": -1.25},
    "WR": {"catching": 5, "gettingOpen": 5, "rushing": 1, "ballSecurity": 1, "constant0": 1.25},
    "TE": {"catching": 2, "gettingOpen": 2, "passBlocking": 2, "runBlocking": 2, "constant0": -0.525},
    "OL": {"passBlocking": 3, "runBlocking": 3, "constant0": 0.75},
    "DL": {"passRushing": 5, "runStopping": 5, "tackling": 1, "constant0": 0.25},
    "LB": {"passRushing": 2, "runStopping": 2, "passCoverage": 1, "tackling": 4, "constant0": -0.75},
    "CB": {"passCoverage": 4.2, "constant0": 1},
    "S": {"passCoverage": 2, "tackling": 1, "constant0": 0.1},
    "K": {"kickingPower": 1, "kickingAccuracy": 1},
    "P": {"puntingPower": 1, "puntingAccuracy": 1},
    "KR": {"speed": 4, "rushing": -0.5, "ballSecurity": 1},
    "PR": {"speed": 4, "rushing": -0.5, "ballSecurity": 2},
}


def composite_ratings(r: dict[str, float]) -> dict[str, float]:
    out = {}
    for key, (components, weights) in COMPOSITE_WEIGHTS.items():
        num = den = 0.0
        for comp, w in zip(components, weights):
            val = comp if isinstance(comp, (int, float)) else r[comp]
            num += val * w
            den += 100 * w
        out[key] = max(0.0, min(1.0, num / den))
    return out


def ovr(comp: dict[str, float], pos: str, player_pos: str) -> float:
    info = OVR_INFO[pos]
    total_coeff = sum(info.values())
    r = sum(c * (0 if k == "constant0" else comp[k]) for k, c in info.items()) / total_coeff * 100
    if r >= 68:
        fudge = 15
    elif r >= 62:
        fudge = 5 + (r - 62) * (10 / 6)
    elif r >= 59:
        fudge = (r - 59) * (5 / 3)
    elif r >= 52:
        fudge = -5 + (r - 52) * (5 / 7)
    elif r >= 40:
        fudge = -15 + (r - 40) * (10 / 12)
    else:
        fudge = -15
    r = max(0, min(100, round(r + fudge)))
    if pos in ("K", "P"):
        r = round(r * 0.75)
    if player_pos == "QB" and pos in ("KR", "PR"):
        r = round(r * 0.5)
    return r


def to_game_player(p: Player, engine_pos: str, on_day: date) -> PlayerGameSim:
    r = fbgm_ratings(p)
    comp = composite_ratings(r)
    ovrs = {pos: ovr(comp, pos, engine_pos) for pos in OVR_INFO}
    return PlayerGameSim(id=p.id, name=p.name, pos=engine_pos, age=p.age_on(on_day), composite=comp, ovrs=ovrs,
                         attributes=dict(p.attributes), playing_through_injury=p.injured)


def build_team(league: League, abbr: str, team_num: int, on_day: date) -> TeamGameSim:
    from ..domain.positions import POSITION_TO_ENGINE

    team: Team = league.teams[abbr]
    roster = [p for p in league.players.values()
              if p.team == abbr and p.roster_status == RosterStatus.ACTIVE and not p.injured]
    cache: dict[str, PlayerGameSim] = {p.id: to_game_player(p, POSITION_TO_ENGINE[p.position], on_day) for p in roster}
    depth_ids = engine_depth(team, {p.id: p for p in roster})
    depth = {pos: [cache[i] for i in ids if i in cache] for pos, ids in depth_ids.items()}
    return TeamGameSim(id=team_num, abbr=abbr, players=list(cache.values()), depth=depth, front=team.front.value)
