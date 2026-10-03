"""상대 성향 기록과 사전 믿음 (ENGINE_DESIGN §6.3, PRD F4-7a·F13-8).

경기마다 엔진이 팀별 콜 요약을 낸다. 시즌 누적 요약 + 지난 시즌 실측 성향으로 상대의 사전 믿음을 만든다.
- p_scout: 1주차는 지난 시즌 실측 성향, 이후 이번 시즌 기록 쪽으로 이동 (경기 수 / (경기 수 + 2))
- w_scout: 0경기 0.3 → 4경기 이상 0.8 (+ 상대 분석 훈련 가산)
"""
from __future__ import annotations

PASS_FAMS = ("screen", "quick", "inter", "deep")
RUN_FAMS = ("inside", "outside")
COVERS = ("C0", "C1", "2M", "C2", "C3", "QTR")


def empty() -> dict:
    return {"games": 0,
            "off": {"plays": 0.0, "pass": 0.0, "xpass": 0.0, "fam": {}, "pa": 0.0},
            "def": {"pass_faced": 0.0, "runs_faced": 0.0, "cov": {}, "blitz": 0.0, "box": {}}}


def accumulate(rec: dict | None, game: dict) -> dict:
    out = empty() if not rec else {"games": rec["games"], "off": {**rec["off"], "fam": dict(rec["off"]["fam"])},
                                   "def": {**rec["def"], "cov": dict(rec["def"]["cov"]), "box": dict(rec["def"]["box"])}}
    out["games"] += 1
    for side in ("off", "def"):
        for k, v in game[side].items():
            if isinstance(v, dict):
                for kk, vv in v.items():
                    out[side][k][kk] = out[side][k].get(kk, 0.0) + vv
            else:
                out[side][k] = out[side][k] + v
    return out


def _shares(counts: dict, keys) -> dict[str, float]:
    tot = sum(counts.get(k, 0.0) for k in keys)
    return {k: counts.get(k, 0.0) / tot for k in keys} if tot else {}


def prior(rec: dict | None, last: dict | None, league: dict | None, scout_add: float = 0.0) -> dict:
    """상대 한 팀에 대한 사전 믿음 요약.

    proe: 기대 대비 패스 비율 편차, fam: 패스·런 패밀리 비중(상대값 배율), blitz/man: 비율, w: 스카우팅 가중치."""
    games = rec["games"] if rec else 0
    a = games / (games + 2.0)
    out = {"w": min(0.8, 0.3 + 0.125 * games) + scout_add, "proe": 0.0, "fam": {}, "blitz": None, "cov": {}}
    lo = (league or {}).get("offense", {})
    ld = (league or {}).get("defense", {})
    last_proe = ((last or {}).get("offense", {}).get("proe", lo.get("proe", 0.0)) - lo.get("proe", 0.0)) if last else 0.0
    season_proe = 0.0
    if rec and rec["off"]["plays"] > 0:
        season_proe = (rec["off"]["pass"] - rec["off"]["xpass"]) / rec["off"]["plays"]
    out["proe"] = a * season_proe + (1 - a) * last_proe
    if rec:
        out["fam"] = _shares(rec["off"]["fam"], PASS_FAMS)
        out["cov"] = _shares(rec["def"]["cov"], COVERS)
        if rec["def"]["pass_faced"]:
            out["blitz"] = rec["def"]["blitz"] / rec["def"]["pass_faced"]
    if last:
        if out["blitz"] is None:
            out["blitz"] = last["defense"]["blitz_rate"]
        else:
            out["blitz"] = a * out["blitz"] + (1 - a) * last["defense"]["blitz_rate"]
        lc = last["defense"]["coverage"]
        out["cov"] = {k: a * out["cov"].get(k, lc.get(k, 0.0)) + (1 - a) * lc.get(k, 0.0) for k in COVERS}
    elif out["blitz"] is None:
        out["blitz"] = ld.get("blitz_rate")
    return out


def report(rec: dict | None, last: dict | None) -> dict:
    """사용자용 스카우팅 리포트 숫자 (F4-7a)."""
    p = prior(rec, last, None)
    off = rec["off"] if rec else None
    return {"games": rec["games"] if rec else 0,
            "pass_rate": (off["pass"] / off["plays"]) if off and off["plays"] else None,
            "proe": p["proe"], "pass_mix": p["fam"], "blitz_rate": p["blitz"], "coverage": p["cov"],
            "last_season": last}
