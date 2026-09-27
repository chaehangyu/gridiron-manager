"""가상 샘플 리그 생성기 (엔진 테스트용, 시드 고정).

실제 데이터와 무관하게 엔진·리그 로직을 검증하기 위한 32팀 리그를 만든다.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from ..domain.depth import auto_depth_chart
from ..domain.models import League, Player, RosterStatus, ScheduledGame, Team
from ..domain.positions import Front, Position
from ..ratings.provisional import generate_attributes

ROSTER_TEMPLATE: dict[Position, int] = {
    Position.QB: 3, Position.RB: 3, Position.FB: 1, Position.WR: 6, Position.TE: 3,
    Position.OT: 4, Position.OG: 4, Position.C: 2,
    Position.EDGE: 5, Position.DT: 4, Position.LB: 5, Position.CB: 6, Position.S: 4,
    Position.K: 1, Position.P: 1, Position.LS: 1,
}
assert sum(ROSTER_TEMPLATE.values()) == 53

# 포지션별 주전 인원 (이 인원까지는 주전급 품질)
STARTERS: dict[Position, int] = {
    Position.QB: 1, Position.RB: 1, Position.FB: 1, Position.WR: 3, Position.TE: 1,
    Position.OT: 2, Position.OG: 2, Position.C: 1,
    Position.EDGE: 2, Position.DT: 2, Position.LB: 2, Position.CB: 3, Position.S: 2,
    Position.K: 1, Position.P: 1, Position.LS: 1,
}

SIZE: dict[Position, tuple[int, int]] = {
    Position.QB: (75, 220), Position.RB: (70, 213), Position.FB: (72, 245), Position.WR: (73, 200),
    Position.TE: (77, 252), Position.OT: (78, 315), Position.OG: (76, 315), Position.C: (75, 305),
    Position.EDGE: (76, 260), Position.DT: (75, 305), Position.LB: (74, 240), Position.CB: (72, 192),
    Position.S: (72, 205), Position.K: (73, 200), Position.P: (74, 215), Position.LS: (74, 240),
}

CITIES = [
    "Aurora", "Bayview", "Cedar Falls", "Driftwood", "Eastport", "Fairhaven", "Granite City", "Harborview",
    "Ironwood", "Jasper", "Kingsbridge", "Lakeshore", "Maple Ridge", "Northgate", "Oakmont", "Pinecrest",
    "Queensport", "Riverton", "Silver Lake", "Thornfield", "Union Bay", "Valemont", "Westbrook", "Yellowstone",
    "Ashford", "Brookhaven", "Coral Bay", "Dunmore", "Elmwood", "Foxborough Hills", "Glenrock", "Highland",
]
NICKNAMES = [
    "Comets", "Mariners", "Lumberjacks", "Otters", "Admirals", "Falcons", "Miners", "Pilots",
    "Ironmen", "Stallions", "Knights", "Waves", "Timberwolves", "Sentinels", "Oaks", "Pioneers",
    "Monarchs", "Rapids", "Storm", "Thorns", "Anchors", "Vipers", "Wranglers", "Bison",
    "Foxes", "Herons", "Sharks", "Dragons", "Elks", "Hounds", "Rockets", "Highlanders",
]
FIRST = ["James", "Marcus", "Tyler", "Jordan", "Devin", "Chris", "Andre", "Kevin", "Brandon", "Jalen", "Isaiah",
         "Cameron", "Darius", "Trevor", "Logan", "Malik", "Nathan", "Ryan", "Xavier", "Zach", "Aaron", "Caleb",
         "Derek", "Elijah", "Garrett", "Hunter", "Jaylen", "Keenan", "Lamar", "Myles", "Noah", "Omar"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis", "Miller", "Wilson", "Moore", "Taylor",
        "Anderson", "Thomas", "Jackson", "White", "Harris", "Martin", "Thompson", "Garcia", "Robinson", "Clark",
        "Lewis", "Walker", "Hall", "Allen", "Young", "King", "Wright", "Scott", "Green", "Baker", "Adams", "Nelson"]

CONF_DIV = [(c, d) for c in ("AFC", "NFC") for d in ("East", "North", "South", "West")]


def _make_player(rng: random.Random, pid: str, pos: Position, quality: float, team: str | None,
                 status: RosterStatus, season: int) -> Player:
    hgt, wgt = SIZE[pos]
    height = hgt + rng.randint(-2, 2)
    weight = wgt + rng.randint(-15, 15)
    age = rng.randint(22, 33)
    exp = max(0, age - 22 - rng.randint(0, 1))
    attrs = generate_attributes(pid, pos, quality, years_exp=exp, height_in=height, weight_lb=weight)
    return Player(
        id=pid,
        name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
        position=pos,
        attributes=attrs,
        birth_date=date(season - age, rng.randint(1, 12), rng.randint(1, 28)),
        height_in=height,
        weight_lb=weight,
        years_exp=exp,
        team=team,
        roster_status=status,
        ratings_source="sample",
    )


def generate_sample_league(seed: int = 2026, season: int = 2026, num_teams: int = 32) -> League:
    rng = random.Random(seed)
    teams: dict[str, Team] = {}
    players: dict[str, Player] = {}
    counter = 0

    for i in range(num_teams):
        abbr = f"S{i + 1:02d}"
        conf, div = CONF_DIV[i % len(CONF_DIV)]
        team = Team(
            abbr=abbr, city=CITIES[i % len(CITIES)], nickname=NICKNAMES[i % len(NICKNAMES)],
            conference=conf, division=div,
            color=f"#{rng.randint(0, 0xFFFFFF):06x}", color2=f"#{rng.randint(0, 0xFFFFFF):06x}",
            front=Front.FOUR_THREE if rng.random() < 0.45 else Front.THREE_FOUR,
        )
        team_strength = rng.gauss(0, 0.8)  # 팀 간 전력 차이
        for pos, n in ROSTER_TEMPLATE.items():
            for j in range(n):
                counter += 1
                base = 12.8 if j < STARTERS[pos] else (10.0 if j < STARTERS[pos] * 2 else 8.5)
                q = base + team_strength + rng.gauss(0, 1.2)
                p = _make_player(rng, f"SMP-{counter:05d}", pos, q, abbr, RosterStatus.ACTIVE, season)
                players[p.id] = p
        # 연습 스쿼드 16명
        ps_positions = [Position.QB, Position.RB, Position.WR, Position.WR, Position.TE, Position.OT, Position.OG,
                        Position.EDGE, Position.DT, Position.LB, Position.LB, Position.CB, Position.CB, Position.S,
                        Position.WR, Position.OT]
        for pos in ps_positions:
            counter += 1
            p = _make_player(rng, f"SMP-{counter:05d}", pos, 7.0 + rng.gauss(0, 1.0), abbr,
                             RosterStatus.PRACTICE_SQUAD, season)
            players[p.id] = p
        teams[abbr] = team

    # FA 풀
    for _ in range(120):
        counter += 1
        pos = rng.choice(list(ROSTER_TEMPLATE))
        p = _make_player(rng, f"SMP-{counter:05d}", pos, 7.5 + rng.gauss(0, 1.2), None,
                         RosterStatus.FREE_AGENT, season)
        players[p.id] = p

    for team in teams.values():
        roster = [p for p in players.values() if p.team == team.abbr]
        team.depth_chart = auto_depth_chart(team, roster)

    league = League(season=season, teams=teams, players=players, source="sample")
    league.schedule = simple_schedule(list(teams), season, rng)
    return league


def simple_schedule(abbrs: list[str], season: int, rng: random.Random, weeks: int = 17) -> list[ScheduledGame]:
    """샘플 리그용 단순 일정: 매주 무작위 대진 (같은 팀과 최대 2번). 실제 리그는 nflverse 일정을 쓴다."""
    games: list[ScheduledGame] = []
    met: dict[frozenset[str], int] = {}
    start = date(season, 9, 13)
    for week in range(1, weeks + 1):
        for _attempt in range(200):
            order = abbrs[:]
            rng.shuffle(order)
            pairs = [(order[i], order[i + 1]) for i in range(0, len(order) - 1, 2)]
            if all(met.get(frozenset(p), 0) < 2 for p in pairs):
                break
        for home, away in pairs:
            met[frozenset((home, away))] = met.get(frozenset((home, away)), 0) + 1
            games.append(ScheduledGame(
                game_id=f"{season}_{week:02d}_{away}_{home}", season=season, week=week, game_type="REG",
                home=home, away=away, gameday=start + timedelta(days=7 * (week - 1)),
                roof="outdoors", surface="grass",
            ))
    return games
