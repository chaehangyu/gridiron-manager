"""주간 부상 관리 (PRD F10-3·F10-5·F10-6, M5b).

경기 후 진단 → 주 시작에 훈련 참여(DNP/Limited/Full)·공식 리포트(Out/Doubtful/Questionable) → 경기 당일 출전 →
주 마감에 회복(팀이 경기를 치른 주만 1경기 차감) → 복귀 시 경기 감각 페널티·재부상 위험 기간.
IR: 예상 결장 4경기 이상이면 자동 등재(사용자는 끌 수 있음), 최소 4경기 후 복귀 지정(시즌 8회)하면 복귀.
"""
from __future__ import annotations

import random
import zlib

from ..domain.models import Injury, League, Player, RosterStatus
from ..engine.injury import cfg, label, severity

SEASON_OUT = 99
STATUS_KO = {"out": "결장", "doubtful": "출전 불투명", "questionable": "출전 의문", "healthy": "정상"}
PRACTICE_KO = {"dnp": "불참", "limited": "제한", "full": "완전"}


def _rng(*key) -> random.Random:
    return random.Random(zlib.crc32(":".join(map(str, key)).encode()))


def rules() -> dict:
    from ..config import load
    return load("league_rules")["ir"]


def diagnose(missed: int, rng: random.Random, medical: float = 12.0) -> tuple[int, int]:
    """진단 범위: 실제 결장 경기를 포함하는 구간. 의료진 수준이 높을수록 좁다 (F10-7, 모두 12)."""
    if missed >= SEASON_OUT:
        return SEASON_OUT, SEASON_OUT
    spread = max(1, round((0.5 + 0.35 * missed) * (1.5 - medical / 20)))
    lo = max(0, missed - int(rng.random() * (spread + 1)))
    return lo, max(lo + 1, lo + spread)


def apply_game(league: League, game, injuries: list[dict]) -> list[Player]:
    """경기에서 생긴 부상을 선수에게 기록한다. 기존 부상(강행 출전 중)은 새 부상으로 덮는다."""
    out = []
    for inj in injuries:
        p = league.players.get(inj["pid"])
        if p is None:
            continue
        missed = SEASON_OUT if inj.get("season_out") else int(inj["missed"])
        if inj["part"] == "concussion":
            p.concussions += 1
            if p.concussions >= 2:
                missed += cfg()["repeat_concussion_extra"]
        rng = _rng(league.season, game.game_id, p.id)
        lo, hi = diagnose(missed, rng)
        p.injury = Injury(body_part=inj["part"], type=label(inj["part"], missed), severity=severity(missed),
                          weeks_out_min=lo, weeks_out_max=hi, weeks_remaining=missed, status="out",
                          season=league.season, week=game.week, game_id=game.game_id)
        out.append(p)
    return out


def weekly_report(league: League, week: int) -> None:
    """주 시작: 훈련 참여와 공식 부상 리포트 (의료진 권고 자동 적용)."""
    for p in league.players.values():
        inj = p.injury
        if inj is None or p.roster_status not in (RosterStatus.ACTIVE, RosterStatus.PRACTICE_SQUAD):
            continue
        r = inj.weeks_remaining
        if r >= 2:
            inj.status, inj.practice = "out", "dnp"
        elif r == 1:
            # 이번 주까지 결장. 일부는 Doubtful로 표기 (실측 Out 40% : Doubtful 6%)
            inj.status = "doubtful" if _rng(league.season, week, p.id).random() < 0.25 else "out"
            inj.practice = "dnp"
        else:
            if inj.body_part == "concussion":
                inj.status, inj.practice = "questionable", "limited"     # 프로토콜 통과 단계
            else:
                inj.status = "questionable"
                tol = p.attributes.get("pain_tolerance", 10.5)
                inj.practice = "limited" if _rng(league.season, week, p.id, "p").random() < 0.75 - 0.02 * tol else "full"


def after_week(league: League, week: int, played: set[str]) -> None:
    """주 마감 (경기를 치른 팀만): 결장 중이면 1경기 차감, 결장이 끝난 상태(Questionable)로 한 주를 보냈으면 회복."""
    c = cfg()
    for p in league.players.values():
        if p.team not in played:
            continue
        if p.rust_games > 0 and p.roster_status == RosterStatus.ACTIVE and not p.injured:
            p.rust_games -= 1                          # 복귀 경기를 치렀다
        inj = p.injury
        if inj is None or inj.week == week:
            continue                                   # 이번 주에 막 다쳤다
        if inj.weeks_remaining >= SEASON_OUT:
            inj.missed += 1
            continue
        if inj.weeks_remaining > 0:
            inj.weeks_remaining -= 1
            inj.missed += 1
            if inj.weeks_remaining == 0 and inj.missed >= 2:
                p.rust_games = 1                       # 다음 경기(복귀전)에 경기 감각 페널티
        else:
            _heal(league, p, week, c)


def _heal(league: League, p: Player, week: int, c: dict) -> None:
    inj = p.injury
    p.reinjury_until = week + c["reinjury_weeks"].get(inj.body_part, c["reinjury_weeks"]["default"])
    p.injury = None


def auto_ir(league: League, week: int, teams: set[str]) -> list[tuple[str, Player, str]]:
    """IR 자동 관리 (AI 팀, 사용자 팀의 의료진 권고): 등재·복귀. (팀, 선수, 'ir'|'activate') 목록."""
    moves = []
    for p in list(league.players.values()):
        if p.team not in teams:
            continue
        inj = p.injury
        if p.roster_status == RosterStatus.ACTIVE and inj and inj.weeks_out_min >= cfg()["ir_auto_weeks"]:
            place_ir(league, p, week)
            moves.append((p.team, p, "ir"))
        elif p.roster_status == RosterStatus.IR and p.ir_week is not None:
            if (inj is None or inj.weeks_remaining == 0) and can_activate(league, p, week)[0]:
                activate(league, p, week)
                moves.append((p.team, p, "activate"))
    return moves


def place_ir(league: League, p: Player, week: int) -> None:
    p.roster_status = RosterStatus.IR
    p.ir_week = week
    if p.injury:
        p.injury.status, p.injury.practice = "out", "dnp"
    if p.team and p.id in league.teams[p.team].elevated:
        league.teams[p.team].elevated.remove(p.id)


def can_activate(league: League, p: Player, week: int) -> tuple[bool, str]:
    r = rules()
    if p.roster_status != RosterStatus.IR:
        return False, "IR 선수가 아닙니다"
    if p.ir_week is None:
        return False, "시즌 시작 전 IR(시즌 아웃)"
    games = sum(1 for g in league.schedule if g.played and p.team in (g.home, g.away) and p.ir_week < g.week <= week)
    if games < r["min_games"]:
        return False, f"최소 {r['min_games']}경기 결장 필요 (현재 {games})"
    if league.ir_returns_used.get(p.team, 0) >= r["return_designations"]:
        return False, f"복귀 지정 {r['return_designations']}회 모두 사용"
    if p.injury and p.injury.weeks_remaining > 0:
        return False, "아직 회복 중"
    return True, ""


def activate(league: League, p: Player, week: int) -> None:
    league.ir_returns_used[p.team] = league.ir_returns_used.get(p.team, 0) + 1
    p.roster_status = RosterStatus.ACTIVE
    p.ir_week = None


def report_rows(league: League, team: str) -> list[dict]:
    rows = []
    for p in league.players.values():
        if p.team != team or p.injury is None:
            continue
        inj = p.injury
        rng = "시즌 아웃" if inj.weeks_out_min >= SEASON_OUT else f"{inj.weeks_out_min}–{inj.weeks_out_max}경기"
        rows.append({"id": p.id, "name": p.name, "pos": p.position.value, "injury": inj.type, "severity": inj.severity,
                     "range": rng, "status": STATUS_KO[inj.status],
                     "practice": "—" if p.roster_status == RosterStatus.IR else PRACTICE_KO[inj.practice],
                     "ir": p.roster_status == RosterStatus.IR, "missed": inj.missed, "sit": inj.sit})
    rows.sort(key=lambda r: (r["ir"], r["status"]))
    return rows
