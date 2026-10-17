"""로스터 운영 (PRD F3-1·F3-8·F3-8b·F3-8c·F8-3, M5c).

53인 로스터 + IR + 연습 스쿼드 16인. 경기 당일 활성 48인(포지션 최소 인원을 먼저 채우고 PR 순).
대체 영입: FA 풀(실제 미계약 선수, 부족하면 대체 선수 수준으로 생성)에서 최저 연봉 1년 계약.
연습 스쿼드 임시 승격: 경기당 2명, 선수당 시즌 3회. AI 팀(과 자동 관리를 켠 사용자 팀)은 매주 같은 FA 풀에서
성적이 나쁜 팀부터 영입한다 (좋은 FA를 먼저 잡는 경쟁, F3-8c).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import load
from ..domain.models import League, Player, RosterStatus
from ..domain.positions import Position
from ..ratings.position_rating import position_rating

GROUPS = {"QB": (Position.QB,), "RB": (Position.RB, Position.FB), "WR": (Position.WR,), "TE": (Position.TE,),
          "OL": (Position.OT, Position.OG, Position.C), "EDGE": (Position.EDGE,), "DT": (Position.DT,),
          "LB": (Position.LB,), "CB": (Position.CB,), "S": (Position.S,), "K": (Position.K,), "P": (Position.P,),
          "LS": (Position.LS,)}
GROUP_OF = {pos: g for g, ps in GROUPS.items() for pos in ps}
# 경기 당일 최소 인원 (합 45) — 나머지 3자리는 PR 순
GAMEDAY_MIN = {"QB": 2, "RB": 3, "WR": 5, "TE": 3, "OL": 8, "EDGE": 4, "DT": 4, "LB": 4, "CB": 5, "S": 4,
               "K": 1, "P": 1, "LS": 1}
# 53인 로스터에서 지키려는 건강한 인원 (AI 영입 기준)
ROSTER_NEED = {"QB": 2, "RB": 3, "WR": 6, "TE": 3, "OL": 9, "EDGE": 4, "DT": 5, "LB": 5, "CB": 5, "S": 4,
               "K": 1, "P": 1, "LS": 1}
# 이 인원 아래로 떨어지면 경기 당일 연습 스쿼드 임시 승격
ELEVATE_BELOW = {"QB": 2, "OL": 7, "K": 1, "P": 1, "LS": 1, "CB": 4, "S": 3, "WR": 4, "EDGE": 3, "DT": 3, "LB": 3,
                 "RB": 2, "TE": 2}


def limits() -> dict:
    return load("league_rules")["roster"]


@dataclass
class Move:
    team: str
    player: Player
    kind: str            # sign | sign_ps | release | promote | demote | elevate
    note: str = ""

    def text(self) -> str:
        ko = {"sign": "영입", "sign_ps": "연습 스쿼드 영입", "release": "방출", "promote": "53인 승격",
              "demote": "연습 스쿼드 강등", "elevate": "경기 임시 승격"}[self.kind]
        return f"{self.player.name}({self.player.position.value}) {ko}" + (f" — {self.note}" if self.note else "")


def active(league: League, team: str) -> list[Player]:
    return league.roster(team, (RosterStatus.ACTIVE,))


def practice_squad(league: League, team: str) -> list[Player]:
    return league.roster(team, (RosterStatus.PRACTICE_SQUAD,))


def healthy(players) -> list[Player]:
    return [p for p in players if not p.injured]


def value(p: Player) -> float:
    return position_rating(p)


def _group_count(players, group: str) -> int:
    return sum(1 for p in players if GROUP_OF.get(p.position) == group)


# ── 경기 당일 활성 명단 (F3-1) ───────────────────────────────
def gameday_actives(league: League, team: str) -> list[Player]:
    """활성 48인: 건강한 53인 + 이번 주 임시 승격. 사용자 비활성 지정은 빼고, 최소 인원 → PR 순."""
    t = league.teams[team]
    pool = healthy(active(league, team))
    pool += [league.players[i] for i in t.elevated if i in league.players and not league.players[i].injured]
    pool = [p for p in pool if p.id not in t.inactives]
    n = limits()["gameday_active"]
    if len(pool) <= n:
        return pool
    ranked = sorted(pool, key=value, reverse=True)
    out, left = [], []
    need = dict(GAMEDAY_MIN)
    for p in ranked:
        g = GROUP_OF.get(p.position)
        if need.get(g, 0) > 0:
            out.append(p)
            need[g] -= 1
        else:
            left.append(p)
    return out + left[: max(0, n - len(out))]


# ── 개별 거래 ────────────────────────────────────────────────
def can_sign(league: League, team: str, p: Player, to_ps: bool = False) -> tuple[bool, str]:
    if p.roster_status != RosterStatus.FREE_AGENT:
        return False, "FA가 아닙니다"
    lim = limits()
    if to_ps:
        if len(practice_squad(league, team)) >= lim["practice_squad"]:
            return False, f"연습 스쿼드 {lim['practice_squad']}인 가득"
    elif len(active(league, team)) >= lim["active_max"]:
        return False, f"53인 가득 — 먼저 방출하세요"
    return True, ""


def sign(league: League, team: str, p: Player, to_ps: bool = False) -> Move:
    p.team = team
    p.roster_status = RosterStatus.PRACTICE_SQUAD if to_ps else RosterStatus.ACTIVE
    p.condition = min(p.condition, 90.0)        # 합류 첫 주 (팀 적응)
    return Move(team, p, "sign_ps" if to_ps else "sign")


def release(league: League, team: str, p: Player) -> Move:
    if p.id in league.teams[team].elevated:
        league.teams[team].elevated.remove(p.id)
    p.team = None
    p.roster_status = RosterStatus.FREE_AGENT
    p.ir_week = None
    return Move(team, p, "release")


def promote(league: League, team: str, p: Player) -> Move:
    if p.id in league.teams[team].elevated:
        league.teams[team].elevated.remove(p.id)
    p.roster_status = RosterStatus.ACTIVE
    return Move(team, p, "promote")


def demote(league: League, team: str, p: Player) -> Move:
    p.roster_status = RosterStatus.PRACTICE_SQUAD
    return Move(team, p, "demote")


def can_elevate(league: League, team: str, p: Player) -> tuple[bool, str]:
    lim = limits()
    t = league.teams[team]
    if p.roster_status != RosterStatus.PRACTICE_SQUAD or p.team != team:
        return False, "우리 팀 연습 스쿼드 선수가 아닙니다"
    if len(t.elevated) >= lim["practice_squad_elevations_per_game"]:
        return False, f"경기당 임시 승격 {lim['practice_squad_elevations_per_game']}명 초과"
    if p.elevations >= lim["elevations_per_player_season"]:
        return False, f"이 선수는 시즌 임시 승격 {lim['elevations_per_player_season']}회를 모두 썼습니다"
    return True, ""


def elevate(league: League, team: str, p: Player) -> Move:
    league.teams[team].elevated.append(p.id)
    p.elevations += 1
    return Move(team, p, "elevate", f"시즌 {p.elevations}회째")


def clear_elevations(league: League, teams) -> None:
    for t in teams:
        league.teams[t].elevated = []


# ── FA 풀 (F3-8c) ────────────────────────────────────────────
def free_agents(league: League, group: str | None = None) -> list[Player]:
    fa = [p for p in league.free_agents() if not p.injured]
    if group:
        fa = [p for p in fa if GROUP_OF.get(p.position) == group]
    return sorted(fa, key=value, reverse=True)


def generate_fa(league: League, group: str) -> Player:
    """FA 풀에 그 포지션이 없으면 대체 선수 수준(PR 8–9)으로 만든다."""
    from datetime import date

    from ..ratings.provisional import generate_attributes, seeded_rng
    pos = GROUPS[group][0]
    n = sum(1 for pid in league.players if pid.startswith("GEN-"))
    pid = f"GEN-{league.season}-{n:04d}"
    rng = seeded_rng(pid, "fa")
    p = Player(id=pid, name=f"대체 선수 {n + 1}", position=pos,
               attributes=generate_attributes(pid, pos, 8.0 + rng.random(), years_exp=2),
               birth_date=date(league.season - 25, 6, 1), years_exp=2, team=None,
               roster_status=RosterStatus.FREE_AGENT, ratings_source="generated")
    league.players[pid] = p
    return p


def best_fa(league: League, group: str) -> Player:
    fa = free_agents(league, group)
    return fa[0] if fa else generate_fa(league, group)


# ── 자동 관리 (AI 팀 + 자동 관리 사용자 팀) ────────────────────
def _need(league: League, team: str) -> str | None:
    """53인 중 건강한 인원이 기준에 가장 많이 모자란 포지션 그룹."""
    h = healthy(active(league, team))
    gaps = {g: n - _group_count(h, g) for g, n in ROSTER_NEED.items()}
    g, gap = max(gaps.items(), key=lambda kv: kv[1])
    return g if gap > 0 else None


def fill_roster(league: League, team: str) -> list[Move]:
    """53인 미만이면 모자란 포지션을 연습 스쿼드 승격 또는 FA 영입으로 채운다."""
    moves = []
    lim = limits()
    while len(active(league, team)) < lim["active_max"]:
        g = _need(league, team) or min(ROSTER_NEED, key=lambda k: _group_count(healthy(active(league, team)), k)
                                       - ROSTER_NEED[k])
        ps = [p for p in healthy(practice_squad(league, team)) if GROUP_OF.get(p.position) == g]
        best_ps = max(ps, key=value, default=None)
        fa = best_fa(league, g)
        if best_ps is not None and value(best_ps) >= value(fa) - 0.5:
            moves.append(promote(league, team, best_ps))
        else:
            moves.append(sign(league, team, fa))
    # 53인이 가득해도 꼭 필요한 자리(QB 2, K·P·LS 1, 그 밖에 기준보다 2명 이상 부족)가 비면
    # 여유가 가장 큰 포지션의 최하위 선수를 방출하고 채운다
    for _ in range(6):
        h = healthy(active(league, team))
        gaps = {g: n - _group_count(h, g) for g, n in ROSTER_NEED.items()}
        crit = [g for g, gap in gaps.items() if gap >= (1 if g in ("QB", "K", "P", "LS") else 2)]
        if not crit:
            break
        g = max(crit, key=lambda k: gaps[k])
        surplus = min(gaps, key=gaps.get)
        if gaps[surplus] >= 0:
            break
        cut = min((p for p in h if GROUP_OF.get(p.position) == surplus), key=value)
        moves.append(release(league, team, cut))
        ps = [p for p in healthy(practice_squad(league, team)) if GROUP_OF.get(p.position) == g]
        best_ps = max(ps, key=value, default=None)
        fa = best_fa(league, g)
        moves.append(promote(league, team, best_ps) if best_ps is not None and value(best_ps) >= value(fa) - 0.5
                     else sign(league, team, fa))
    # 연습 스쿼드 빈자리 채우기 (승격으로 빈 곳)
    while len(practice_squad(league, team)) < lim["practice_squad"]:
        g = min(ROSTER_NEED, key=lambda k: _group_count(practice_squad(league, team), k) - ROSTER_NEED[k] / 3)
        moves.append(sign(league, team, best_fa(league, g), to_ps=True))
    return moves


def gameday_elevations(league: League, team: str) -> list[Move]:
    """경기 당일 건강한 인원이 모자란 포지션은 연습 스쿼드에서 임시 승격."""
    moves = []
    h = healthy(active(league, team))
    for g, n in ELEVATE_BELOW.items():
        short = n - _group_count(h, g) - sum(1 for i in league.teams[team].elevated
                                             if GROUP_OF.get(league.players[i].position) == g)
        for _ in range(max(0, short)):
            cands = sorted((p for p in healthy(practice_squad(league, team))
                            if GROUP_OF.get(p.position) == g and can_elevate(league, team, p)[0]),
                           key=value, reverse=True)
            if not cands:
                break
            moves.append(elevate(league, team, cands[0]))
    return moves


def weekly_moves(league: League, teams: list[str]) -> dict[str, list[Move]]:
    """주 마감 자동 로스터 관리. 성적이 나쁜 팀부터 (웨이버 순서처럼) FA를 고른다."""
    from .standings import Table
    tb = Table.from_league(league)
    order = sorted(teams, key=lambda t: (tb.rec(t).pct, t))
    return {t: fill_roster(league, t) for t in order}
