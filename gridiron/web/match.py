"""매치 센터·경기 결과 데이터 (PRD F6, S8·S9): 저장된 플레이 로그 → 중계 타임라인, 드라이브 차트, 박스스코어."""
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session, select

from ..db import schema as S
from ..db.store import engine_for
from ..engine.commentary import clock_str, render

PLAY_TYPES = {"run", "pass", "punt", "fieldGoal"}
TURNOVER = {"interception"}


def load_events(path: Path, game_id: str) -> list[dict]:
    with Session(engine_for(path)) as s:
        return [r.event for r in s.exec(select(S.PlayRow).where(S.PlayRow.game_id == game_id).order_by(S.PlayRow.seq))]


def box(path: Path, game_id: str) -> tuple[dict, list]:
    with Session(engine_for(path)) as s:
        teams = {r.team: r.stats for r in s.exec(select(S.TeamGameStatsRow).where(S.TeamGameStatsRow.game_id == game_id))}
        players = [(r.player_id, r.team, r.stats) for r in
                   s.exec(select(S.PlayerGameStatsRow).where(S.PlayerGameStatsRow.game_id == game_id))]
    return teams, players


def _highlight(ev: dict) -> bool:
    t = ev["type"]
    return bool(ev.get("td") or ev.get("safety") or t in ("fieldGoal", "interception", "sack", "injury", "turnoverOnDowns",
                                                          "quarter", "gameOver", "overtime", "twoMinuteWarning")
                or (t == "fumbleRecovery" and ev.get("lost")) or (t in ("passComplete", "run") and ev.get("yds", 0) >= 20))


def timeline(events: list[dict], abbrs: list[str]) -> dict:
    """문장 + 그 시점 스코어보드 상태 목록, 승률 추이, 3rd down, 드라이브."""
    st: dict = {}
    frames, drives = [], []
    pts = [0, 0]
    third = {0: [0, 0], 1: [0, 0]}
    wp_series, report = [], {}
    pending_third = None
    cur = None
    for ev in events:
        typ = ev["type"]
        if typ == "wpSeries":
            wp_series = ev["series"]
            continue
        if typ == "tacticsReport":
            report = ev["report"]
            continue
        if ev.get("pts"):
            pts = ev["pts"]
        if typ == "clock":
            if pending_third is not None:
                t0 = pending_third
                if ev.get("t") == t0 and ev.get("down") == 1:
                    third[t0][0] += 1
                pending_third = None
            pt = ev.get("playType")
            if ev.get("down") == 3 and pt in ("run", "pass"):
                third[ev["t"]][1] += 1
                pending_third = ev["t"]
            if pt in ("run", "pass", "punt", "fieldGoal"):
                if cur is None or cur["t"] != ev["t"]:
                    if cur:
                        drives.append(cur)
                    cur = {"t": ev["t"], "team": abbrs[ev["t"]], "q": ev["quarter"], "start": ev["scrimmage"],
                           "clock": clock_str(ev["clock"]), "plays": 0, "end": ev["scrimmage"], "result": "진행"}
                if pt in ("run", "pass"):
                    cur["plays"] += 1
                cur["end"] = ev["scrimmage"]
        if cur is not None:
            if ev.get("td") and typ in ("passComplete", "run"):
                cur["result"], cur["end"] = "TD", 100
            elif typ == "fieldGoal":
                cur["result"] = "FG" if ev.get("made") else "FG 실패"
            elif typ == "punt":
                cur["result"] = "펀트"
            elif typ in TURNOVER or (typ == "fumbleRecovery" and ev.get("lost")):
                cur["result"] = "턴오버"
            elif typ == "turnoverOnDowns":
                cur["result"] = "다운 실패"
            elif typ in ("quarter", "gameOver") and cur["result"] == "진행" and ev.get("quarter") in (3, 5, None):
                cur["result"] = "전반 종료" if typ == "quarter" else "경기 종료"
        line = render(ev, abbrs, st)
        if line is None:
            continue
        frames.append({"text": line.strip("\n"), "q": ev.get("quarter", st.get("quarter", 1)),
                       "clock": clock_str(ev["clock"]) if "clock" in ev else "", "pts": list(pts),
                       "pos": st.get("scrimmage"), "t": st.get("t"), "down": st.get("down"), "toGo": st.get("toGo"),
                       "wp": st.get("home_wp"), "hl": _highlight(ev), "td": bool(ev.get("td")),
                       "head": typ in ("quarter", "overtime", "gameOver")})
    if cur:
        drives.append(cur)
    for d in drives:
        d["yds"] = (d["end"] - d["start"]) if d["result"] != "턴오버" else d["end"] - d["start"]
        d["start_txt"] = f"{d['team']} {d['start']}" if d["start"] <= 50 else f"상대 {100 - d['start']}"
    return {"frames": frames, "drives": drives, "third": third, "wp": wp_series, "report": report}
