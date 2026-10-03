"""전술 궁합 (PRD F4-8c·d, ENGINE_DESIGN §4.5).

선수 궁합 = 현재 전술의 콜 비율로 계산한 그 선수의 능력 ÷ 그 선수에게 가장 유리한 콜로 계산한 능력.
엔진과 같은 콜별 가중치(config/scheme_weights.yaml)를 쓴다. 0.85 미만 주전은 경고.
"""
from __future__ import annotations

from ..domain.models import League, Player
from ..domain.positions import POSITION_TO_ENGINE
from .model import MAN_COVERS, Tactics

WARN = 0.85


def _w(group: str, call: str) -> dict[str, float]:
    from ..engine.adjust import scheme
    return scheme(group, call)


def _rate(p: Player, weights: dict[str, float]) -> float:
    tot = sum(weights.values())
    return sum(p.attributes[k] * w for k, w in weights.items()) / tot


def shares(t: Tactics, front: str) -> dict:
    """전술이 정하는 대표 콜 비율 (1st & 10, 11 퍼스넬 기준)."""
    from ..engine.ai.coordinator import identity_coverage
    from ..engine.outcome.data_model import RUN_STYLE_ZONE
    cov = identity_coverage("1st", "11", t, {})
    man = sum(v for (c, _), v in cov.items() if c in MAN_COVERS)
    o = t.offense
    base = {"screen": 0.09, "quick": 0.38, "inter": 0.35, "deep": 0.18}
    mult = {"screen": o.screen, "quick": o.short, "inter": o.mid, "deep": o.deep}
    mix = {f: base[f] * mult[f] for f in base}
    z = sum(mix.values())
    return {"zone_run": RUN_STYLE_ZONE[o.run_style], "man": man, "depth": {f: v / z for f, v in mix.items()},
            "front": front}


def player_fit(p: Player, sh: dict) -> tuple[float, str] | None:
    pos = POSITION_TO_ENGINE[p.position]
    if pos in ("OL",) or p.position.value == "TE":
        z, g = _rate(p, _w("run_block", "zone")), _rate(p, _w("run_block", "gap"))
        cur = sh["zone_run"] * z + (1 - sh["zone_run"]) * g
        return cur / max(z, g), "존 블록" if z >= g else "갭 블록"
    if pos == "RB":
        z, g = _rate(p, _w("carry", "zone")), _rate(p, _w("carry", "gap"))
        cur = sh["zone_run"] * z + (1 - sh["zone_run"]) * g
        return cur / max(z, g), "존 러너" if z >= g else "파워 러너"
    if pos in ("CB", "S", "LB"):
        m, zn = _rate(p, _w("coverage", "man")), _rate(p, _w("coverage", "zone"))
        cur = sh["man"] * m + (1 - sh["man"]) * zn
        return cur / max(m, zn), "맨 커버" if m >= zn else "존 커버"
    if pos == "QB" or p.position.value == "WR":
        group = "qb" if pos == "QB" else "receiver"
        r = {f: _rate(p, _w(group, f)) for f in sh["depth"]}
        cur = sum(sh["depth"][f] * r[f] for f in r)
        best = max(r, key=r.get)
        return cur / r[best], f"{best} 특화"
    if pos == "DL":
        a, b = _rate(p, _w("pass_rush", "4-3")), _rate(p, _w("pass_rush", "3-4"))
        cur = a if sh["front"] == "4-3" else b
        return cur / max(a, b), "4-3 러셔" if a >= b else "3-4 러셔"
    return None


def team_fit(league: League, abbr: str, tactics: Tactics | None = None) -> dict:
    team = league.teams[abbr]
    t = tactics or team.tactics
    sh = shares(t, team.front.value)
    starters = {pid for ids in team.depth_chart.values() for pid in ids[:1]}
    rows, groups = [], {}
    for pid in starters:
        p = league.players.get(pid)
        if p is None:
            continue
        res = player_fit(p, sh)
        if res is None:
            continue
        fit, style = res
        rows.append({"id": pid, "name": p.name, "pos": p.position.value, "fit": round(fit, 3), "style": style})
        groups.setdefault(POSITION_TO_ENGINE[p.position], []).append(fit)
    rows.sort(key=lambda r: r["fit"])
    return {"shares": sh, "players": rows, "warnings": [r for r in rows if r["fit"] < WARN],
            "groups": {g: round(sum(v) / len(v), 3) for g, v in groups.items()},
            "team": round(sum(r["fit"] for r in rows) / max(1, len(rows)), 3)}
