"""한국어 텍스트 중계 (PRD F6, D13: 기록형 + 주요 장면 강조). 풋볼 용어는 영어 병기."""
from __future__ import annotations

ORDINAL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}


def clock_str(minutes: float) -> str:
    total = max(0, round(minutes * 60))
    return f"{total // 60:02d}:{total % 60:02d}"


def field_pos(scrimmage: float, off: str, deff: str) -> str:
    s = round(scrimmage)
    if s == 50:
        return "50"
    return f"{off} {s}" if s < 50 else f"{deff} {100 - s}"


def render(ev: dict, abbrs: list[str], state: dict) -> str | None:
    """이벤트 하나를 문장으로. state는 직전 clock 이벤트(다운·거리)를 보관한다."""
    t = ev.get("t")
    team = abbrs[t] if t is not None else ""
    names = ev.get("names", [])
    typ = ev["type"]
    y = ev.get("yds", 0)
    star = "★ " if ev.get("td") or ev.get("safety") else ""
    if typ == "clock":
        state.update(ev)
        return None
    if typ == "quarter":
        return f"\n── {ev['quarter']}쿼터 ──"
    if typ == "overtime":
        return f"\n── 연장 {ev['overtimes']} ──"
    if typ == "gameOver":
        return "\n── 경기 종료 ──"
    if typ == "twoMinuteWarning":
        return "   [2분 경고]"
    if typ == "timeout":
        return f"   {team} 타임아웃 (남은 {ev['numLeft']}개)"
    if typ == "kickoff":
        if ev.get("touchback"):
            return f"{team} 킥오프 — {names[0]} · 터치백"
        spot = f"엔드존 {abs(y)}야드 깊이" if y < 0 else ("골라인" if y == 0 else f"{y}야드 라인")
        return f"{team} 킥오프 — {names[0]} · {spot}"
    if typ == "kickoffReturn":
        return f"{star}{names[0]} 킥오프 리턴 {y}야드" + (" 터치다운!" if ev.get("td") else "")
    if typ == "onsideKick":
        return f"{team} 온사이드 킥 시도 — {names[0]}"
    if typ == "onsideKickRecovery":
        return f"   온사이드 킥 {'성공' if ev['success'] else '실패'} — {names[0]} 확보" + (" 터치다운!" if ev.get("td") else "")
    if typ == "punt":
        return f"{team} 펀트 — {names[0]} {y}야드" + (" · 터치백" if ev.get("touchback") else "")
    if typ == "puntReturn":
        return f"{star}{names[0]} 펀트 리턴 {y}야드" + (" 터치다운!" if ev.get("td") else "")
    prefix = ""
    if state.get("down") is not None and typ in ("passComplete", "passIncomplete", "run", "sack", "kneel"):
        off = abbrs[state["t"]]
        deff = abbrs[1 - state["t"]]
        to_go = "Goal" if state["scrimmage"] + state["toGo"] >= 100 else round(state["toGo"])
        prefix = f"[{ORDINAL.get(state['down'], state['down'])} & {to_go} · {field_pos(state['scrimmage'], off, deff)}] "
    if typ == "passComplete":
        s = f"{prefix}{star}{names[0]} → {names[1]} 패스 성공 {y}야드"
        return s + (" 터치다운!" if ev.get("td") else "") + (" 세이프티!" if ev.get("safety") else "")
    if typ == "passIncomplete":
        return f"{prefix}{names[0]} → {names[1]} 패스 실패"
    if typ == "run":
        who = f"{names[0]} 스크램블" if ev.get("scramble") else f"{names[0]} 런"
        s = f"{prefix}{star}{who} {y}야드"
        return s + (" 터치다운!" if ev.get("td") else "") + (" 세이프티!" if ev.get("safety") else "")
    if typ == "sack":
        return f"{prefix}{star}{names[1]} 색! {names[0]} {abs(y)}야드 손실" + (" 세이프티!" if ev.get("safety") else "")
    if typ == "kneel":
        return f"{prefix}{names[0]} 무릎 꿇기"
    if typ == "interception":
        return f"   ★ 인터셉션! {names[0]} ({team})"
    if typ == "interceptionReturn":
        if ev.get("touchback"):
            return "   엔드존에서 잡아 터치백"
        return f"{star}   {names[0]} 리턴 {y}야드" + (" 픽식스 터치다운!" if ev.get("td") else "")
    if typ == "fumble":
        return f"   ★ 펌블! {names[0]} (강제: {names[1]})"
    if typ == "fumbleRecovery":
        who = f"{names[0]} ({team}) 확보"
        extra = " 터치다운!" if ev.get("td") else (" 터치백" if ev.get("touchback") else "")
        return f"{star}   {who}" + (" · 턴오버" if ev.get("lost") else "") + extra
    if typ == "fieldGoal":
        return f"{star}{team} {names[0]} {y}야드 필드골 {'성공' if ev['made'] else '실패'}"
    if typ == "extraPoint":
        return f"   PAT {'성공' if ev['made'] else '실패'}"
    if typ == "twoPointConversion":
        return f"   {team} 2점 전환 시도"
    if typ == "twoPointConversionFailed":
        return "   2점 전환 실패"
    if typ == "goingForItOn4th":
        return f"   {team} 4th down 공격 강행"
    if typ == "turnoverOnDowns":
        return f"   턴오버 온 다운스 — {team} 공격권"
    if typ == "penalty":
        dec = {"accept": "수락", "decline": "거부"}.get(ev["decision"], ev["decision"])
        who = f" ({ev['names'][0]})" if ev.get("names") else ""
        if ev.get("offsetStatus") == "offset":
            return f"   🚩 {abbrs[ev['t']]} {ev['penaltyNameKo']}{who} — 상쇄"
        return f"   🚩 {abbrs[ev['t']]} {ev['penaltyNameKo']}{who} {ev['yds']}야드 — {dec}"
    if typ == "injury":
        return f"   ✚ 부상: {names[0]} ({team})"
    return None


def render_game(events: list[dict], abbrs: list[str]) -> list[str]:
    state: dict = {}
    lines = []
    for ev in events:
        line = render(ev, abbrs, state)
        if line is not None:
            clock = f"{clock_str(ev['clock'])} " if "clock" in ev and ev["type"] not in ("quarter", "overtime", "gameOver") else ""
            lines.append(f"{clock}{line}" if clock and not line.startswith("\n") else line)
    return lines
