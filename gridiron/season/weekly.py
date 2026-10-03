"""주간 진행 (PRD §4 핵심 루프, F11, M4).

주 시작(prepare_week): 훈련 적용 → 숙련도·이번 주 준비값·컨디션. 지난주에 안 쓴 영역 숙련도 감소.
경기 후(after_game): 쓴 영역 숙련도 +2, 콜 성향 기록(상대 스카우팅용), 출전 선수 컨디션 감소.
"""
from __future__ import annotations

from ..domain.models import League
from ..tactics import familiarity, scouting, training

GAME_FATIGUE_PER_SNAP = 0.12     # 스냅 1개당 컨디션 감소 (70스냅 ≈ −8.4)
WEEKLY_RECOVERY = 8.0


def used_domains(team) -> list[str]:
    """지금 전술이 주로 쓰는 영역 (자동 훈련 초점 후보)."""
    if team.usage:
        shares = familiarity.usage_shares(team.usage)
        used = [d for d, s in shares.items() if s >= 0.2]
        if used:
            return used
    o, d = team.tactics.offense, team.tactics.defense
    out = ["run_gap" if o.run_style == "gap" else "run_zone", "pass_quick", "pass_inter"]
    out.append("cov_man" if d.man_zone > 0.2 else "cov_zone")
    if d.blitz > 1.2:
        out.append("blitz")
    return out


def prepare_week(league: League, week: int) -> None:
    if league.prepared_week >= week:
        return
    for team in league.teams.values():
        fam = familiarity.weekly_decay(team.familiarity, team.usage) if team.usage else team.familiarity
        fam, prep, cond = training.apply_week(team.training, fam, used_domains(team))
        team.familiarity = {k: round(v, 2) for k, v in fam.items()}
        team.prep = prep
        for p in league.roster(team.abbr):
            p.condition = max(0.0, min(100.0, p.condition + WEEKLY_RECOVERY + cond))
    league.prepared_week = week


def after_game(league: League, report: dict, box_players: dict) -> None:
    for abbr, rep in report.items():
        team = league.teams[abbr]
        team.familiarity = familiarity.after_game(team.familiarity, rep["usage"])
        team.usage = dict(rep["usage"])
        team.scouting = scouting.accumulate(team.scouting or None, rep["summary"])
        team.prep = {}
    for pid, (_, st) in box_players.items():
        p = league.players.get(pid)
        if p is not None:
            p.condition = max(0.0, p.condition - GAME_FATIGUE_PER_SNAP * st.get("snaps", 0))
