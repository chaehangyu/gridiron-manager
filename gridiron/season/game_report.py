"""경기 후 리포트 (PRD F6-5 전술 효과, F6-6 선수 평점).

플레이 로그(clock 이벤트의 EP + 콜 정보 x_*)로 플레이마다 EPA를 계산해 팀별로
공격 플레이 패밀리·상대 커버리지별 시도·성공률(EPA>0)·EPA, 쿼터별 효율 추이를 만든다.
선수 평점은 박스스코어 기록으로 FM식 10점 만점(6.0 = 평균 활약)을 낸다.
"""
from __future__ import annotations

FAMILY_KO = {"quick": "퀵 패스", "inter": "인터미디어트 패스", "deep": "딥 패스", "screen": "스크린", "pa": "플레이액션",
             "inside": "인사이드 런", "outside": "아웃사이드 런", "scramble": "QB 스크램블"}
COVER_KO = {"C0": "Cover 0", "C1": "Cover 1", "2M": "2-Man", "C2": "Cover 2", "C3": "Cover 3", "QTR": "Quarters"}


def derive(s: dict) -> dict:
    """원본 박스 키에서 합계 기록 (태클·필드골)."""
    out = dict(s)
    out["defTck"] = s.get("defTckSolo", 0) + s.get("defTckAst", 0)
    out["fg"] = sum(v for k, v in s.items() if k.startswith("fg") and k[2:].isdigit())
    out["fga"] = sum(v for k, v in s.items() if k.startswith("fga") and k[3:].isdigit())
    return out


def _family(evs: list[dict]) -> tuple[str | None, str | None]:
    """한 플레이의 이벤트들 → (공격 패밀리, 상대 커버리지)."""
    for e in evs:
        if e["type"] == "dropback":
            fam = "pa" if e.get("x_pa") else e.get("x_call")
            return fam, e.get("x_cov")
        if e["type"] == "run":
            return e.get("x_family"), None
    return None, None


def play_epa(events: list[dict]) -> list[dict]:
    """scrimmage 플레이별 {t, q, family, cover, epa}. 득점은 TD 7·FG 3·세이프티 2로 본다."""
    clocks = [i for i, e in enumerate(events) if e["type"] == "clock"]
    plays = []
    for n, i in enumerate(clocks):
        c = events[i]
        if c.get("playType") not in ("run", "pass") or c.get("ep") is None:
            continue
        j = clocks[n + 1] if n + 1 < len(clocks) else len(events)
        fam, cov = _family(events[i + 1:j])
        if fam is None:
            continue
        t = c["t"]
        nxt = events[j] if j < len(events) else None
        before = c.get("pts") or [0, 0]
        after = (nxt.get("pts") if nxt else None) or events[-1].get("pts") or before
        d_off, d_def = after[t] - before[t], after[1 - t] - before[1 - t]
        ep = c["ep"]
        if d_off >= 6:
            epa = 7 - ep
        elif d_off >= 3:
            epa = 3 - ep
        elif d_def >= 6:
            epa = -7 - ep
        elif d_def >= 2:
            epa = -2 - ep
        elif nxt is None or nxt.get("ep") is None:
            epa = 0.0
        elif nxt.get("t") == t:
            epa = nxt["ep"] - ep
        else:
            epa = -nxt["ep"] - ep
        plays.append({"t": t, "q": min(c.get("quarter", 1), 5), "family": fam, "cover": cov, "epa": epa})
    return plays


def _agg(rows) -> dict:
    n = len(rows)
    return {"n": n, "success": sum(r["epa"] > 0 for r in rows) / n if n else 0.0,
            "epa": sum(r["epa"] for r in rows) / n if n else 0.0, "total": sum(r["epa"] for r in rows)}


def tactical_report(events: list[dict], abbrs: list[str]) -> dict:
    """팀(0=홈, 1=원정)별 공격 패밀리, 상대 커버리지, 쿼터별 효율."""
    plays = play_epa(events)
    out = {}
    for t in (0, 1):
        mine = [p for p in plays if p["t"] == t]
        fams = {}
        for f in ("inside", "outside", "scramble", "quick", "inter", "deep", "screen", "pa"):
            rows = [p for p in mine if p["family"] == f]
            if rows:
                fams[FAMILY_KO.get(f, f)] = _agg(rows)
        covs = {}
        for c in COVER_KO:
            rows = [p for p in mine if p["cover"] == c]
            if rows:
                covs[COVER_KO[c]] = _agg(rows)
        quarters = {q: _agg([p for p in mine if p["q"] == q]) for q in sorted({p["q"] for p in mine})}
        out[abbrs[t]] = {"overall": _agg(mine), "families": fams, "covers": covs, "quarters": quarters,
                         "run": _agg([p for p in mine if p["family"] in ("inside", "outside")]),
                         "pass": _agg([p for p in mine if p["family"] in ("quick", "inter", "deep", "screen", "pa")])}
    return out


# ── 선수 평점 (F6-6) ────────────────────────────────────────
def player_rating(pos: str, s: dict, team: dict, won: bool) -> float | None:
    """FM식 10점 만점. 기록이 거의 없는 선수는 None."""
    s = derive(s)
    if s.get("snaps", 0) < 8 and not any(s.get(k) for k in ("pss", "rus", "rec", "defTck", "fga", "pnt")):
        return None
    r = 6.0
    if pos == "QB":
        r += (s.get("pssYds", 0) - 220) / 90 + 0.5 * s.get("pssTD", 0) - 0.75 * s.get("pssInt", 0) \
            - 0.12 * s.get("pssSk", 0) + s.get("rusYds", 0) / 60 + 0.5 * s.get("rusTD", 0) - 0.6 * s.get("fmbLost", 0)
        if s.get("pss"):
            r += (s.get("pssCmp", 0) / s["pss"] - 0.64) * 3
    elif pos in ("RB", "FB"):
        r += (s.get("rusYds", 0) - (45 if pos == "RB" else 5)) / 45 + 0.6 * s.get("rusTD", 0) + s.get("recYds", 0) / 45 \
            + 0.5 * s.get("recTD", 0) - 0.8 * s.get("fmbLost", 0)
    elif pos in ("WR", "TE"):
        r += (s.get("recYds", 0) - (35 if pos == "WR" else 22)) / 40 + 0.6 * s.get("recTD", 0) + 0.08 * s.get("rec", 0) \
            - 0.05 * max(0, s.get("tgt", 0) - s.get("rec", 0)) - 0.8 * s.get("fmbLost", 0)
        if pos == "TE":
            r += 0.4 * (s.get("rbw", 0) / s["rba"] - 0.5) * 2 if s.get("rba") else 0
    elif pos in ("OT", "OG", "C"):
        r += 0.5 - 0.6 * s.get("skAlw", 0) - 0.08 * s.get("pen", 0) * 5
        if s.get("pba"):
            r += (s.get("pbw", 0) / s["pba"] - 0.85) * 4
        if s.get("rba"):
            r += (s.get("rbw", 0) / s["rba"] - 0.5) * 2
        r += (team.get("rusYds", 0) / max(1, team.get("rus", 1)) - 4.2) * 0.15
    elif pos in ("K",):
        r += 0.35 * s.get("fg", 0) - 0.9 * (s.get("fga", 0) - s.get("fg", 0)) + 0.05 * s.get("xp", 0) \
            - 0.6 * (s.get("xpa", 0) - s.get("xp", 0))
    elif pos in ("P",):
        if s.get("pnt"):
            r += (s.get("pntYds", 0) / s["pnt"] - 47) / 5 + 0.15 * s.get("pntIn20", 0) - 0.15
    else:   # 수비
        r += 0.09 * s.get("defTck", 0) + 0.25 * s.get("defTckLoss", 0) + 0.8 * s.get("defSk", 0) \
            + 1.0 * s.get("defInt", 0) + 0.3 * s.get("defPssDef", 0) + 0.7 * s.get("defFmbFrc", 0) \
            + 0.5 * s.get("defFmbRec", 0) - 0.4
    r += 0.3 if won else -0.1
    return round(max(3.0, min(10.0, r)), 1)


def player_ratings(league, game, players: list[tuple[str, str, dict]], teams: dict) -> list[dict]:
    """[(pid, 팀, 박스)] → 평점 목록 (높은 순)."""
    out = []
    winner = game.home if game.home_score > game.away_score else game.away if game.away_score > game.home_score else None
    for pid, abbr, s in players:
        p = league.players.get(pid)
        if p is None:
            continue
        r = player_rating(p.position.value, s, teams.get(abbr, {}), abbr == winner)
        if r is not None:
            out.append({"id": pid, "name": p.name, "pos": p.position.value, "team": abbr, "rating": r})
    out.sort(key=lambda x: -x["rating"])
    return out
