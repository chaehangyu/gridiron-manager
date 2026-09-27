"""페널티 정의 (원본 penalties.ts).

numPerSeason은 원본의 NFL 시즌 기준 빈도다. M2에서 nflverse pbp 페널티 기록으로 다시 보정한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

ALL_RETURN_TYPES = ["kickoffReturn", "fieldGoal", "punt", "puntReturn", "pass", "run"]


@dataclass
class Penalty:
    name: str
    name_ko: str
    side: str  # offense | defense
    play_types: list[str]
    num_per_season: int
    yds: int
    automatic_first_down: bool = False
    not_ball_carrier: bool = False
    spot_foul: bool = False
    tack_on: bool = False
    pos_odds: dict[str, float] | None = None  # None: 선수 미지정(딜레이 오브 게임 등), {}: 필드 전원 동일 확률
    prob_per_play: float = field(default=0.0)


PENALTIES: list[Penalty] = [
    Penalty("Holding", "홀딩", "offense", ALL_RETURN_TYPES, 709, 10,
            pos_odds={"OL": 0.83, "TE": 0.1, "WR": 0.05, "RB": 0.02}, not_ball_carrier=True),
    Penalty("False start", "폴스 스타트", "offense", ["beforeSnap"], 560, 5,
            pos_odds={"OL": 0.92, "TE": 0.05, "WR": 0.02, "RB": 0.01}),
    Penalty("Pass interference", "패스 방해", "defense", ["pass"], 237, 0,
            pos_odds={"CB": 0.6, "S": 0.3, "LB": 0.1}, automatic_first_down=True, spot_foul=True),
    Penalty("Holding", "홀딩", "defense", ["pass", "run"], 236, 5,
            pos_odds={"DL": 0.25, "LB": 0.25, "S": 0.25, "CB": 0.25}, automatic_first_down=True),
    Penalty("Unnecessary roughness", "불필요한 거친 행위", "defense", ALL_RETURN_TYPES, 150, 15,
            pos_odds={"DL": 0.25, "LB": 0.25, "S": 0.25, "CB": 0.25}, automatic_first_down=True, tack_on=True),
    Penalty("Unnecessary roughness", "불필요한 거친 행위", "offense", ALL_RETURN_TYPES, 50, 15,
            pos_odds={"QB": 0.01, "RB": 0.14, "WR": 0.3, "TE": 0.15, "OL": 0.4}),
    Penalty("Illegal block in the back", "백 블록", "offense", ["puntReturn"], 184, 10,
            pos_odds={"DL": 0.4, "S": 0.6}),
    Penalty("Neutral zone infraction", "뉴트럴 존 침범", "defense", ["beforeSnap"], 143, 5,
            pos_odds={"DL": 0.85, "LB": 0.15}),
    Penalty("Offsides", "오프사이드", "defense", ["fieldGoal", "punt", "pass", "run"], 143, 5,
            pos_odds={"DL": 0.85, "LB": 0.15}),
    Penalty("Roughing the passer", "러핑 더 패서", "defense", ["pass"], 114, 15,
            pos_odds={"DL": 0.7, "LB": 0.24, "S": 0.04, "CB": 0.02}, automatic_first_down=True, tack_on=True),
    Penalty("Delay of game", "딜레이 오브 게임", "offense", ["beforeSnap"], 111, 5),
    Penalty("Delay of game", "딜레이 오브 게임", "defense", ["beforeSnap"], 1, 5),
    Penalty("Face mask", "페이스 마스크", "defense", ["pass", "run", "kickoffReturn", "puntReturn"], 80, 15,
            pos_odds={"LB": 0.6, "DL": 0.2, "S": 0.1, "CB": 0.1}, automatic_first_down=True, tack_on=True),
    Penalty("Face mask", "페이스 마스크", "offense", ["pass", "run", "kickoffReturn", "puntReturn"], 8, 15,
            pos_odds={"RB": 0.3, "WR": 0.3, "OL": 0.25, "TE": 0.15}, tack_on=True),
    Penalty("Pass interference", "공격 패스 방해", "offense", ["pass"], 83, 10,
            pos_odds={"WR": 0.82, "TE": 0.16, "RB": 0.02}),
    Penalty("Illegal formation", "일리걸 포메이션", "offense", ["pass", "run"], 71, 5),
    Penalty("Illegal use of hands", "일리걸 유즈 오브 핸즈", "defense", ["pass", "run"], 36, 5,
            pos_odds={}, automatic_first_down=True),
    Penalty("Illegal use of hands", "일리걸 유즈 오브 핸즈", "offense", ["pass", "run"], 35, 10,
            pos_odds={"RB": 0.1, "WR": 0.3, "OL": 0.5, "TE": 0.1}),
    Penalty("Unsportsmanlike conduct", "비신사적 행위", "defense", ["beforeSnap"], 27, 15,
            pos_odds={}, automatic_first_down=True, tack_on=True),
    Penalty("Unsportsmanlike conduct", "비신사적 행위", "offense", ["beforeSnap"], 26, 15, pos_odds={}, tack_on=True),
    Penalty("Illegal shift", "일리걸 시프트", "offense", ["beforeSnap"], 43, 5,
            pos_odds={"RB": 0.2, "WR": 0.6, "TE": 0.2}),
    Penalty("Illegal contact", "일리걸 컨택트", "defense", ["pass"], 43, 5,
            pos_odds={"LB": 0.1, "S": 0.1, "CB": 0.8}, automatic_first_down=True),
    Penalty("Too many men on the field", "12명 출전", "defense", ["pass", "run", "fieldGoal"], 42, 5, pos_odds={}),
    Penalty("Too many men on the field", "12명 출전", "offense", ["pass", "run", "fieldGoal"], 6, 5, pos_odds={}),
    Penalty("Encroachment", "인크로치먼트", "defense", ["beforeSnap"], 40, 5, pos_odds={"DL": 1}),
    Penalty("Taunting", "도발", "offense", ["kickoffReturn", "fieldGoal", "puntReturn", "pass", "run"], 12, 15,
            pos_odds={}, tack_on=True),
    Penalty("Taunting", "도발", "defense", ["kickoffReturn", "fieldGoal", "puntReturn", "pass", "run"], 11, 15,
            pos_odds={}, automatic_first_down=True, tack_on=True),
    Penalty("Lowering the head to initiate contact", "헬멧 충돌", "defense",
            ["kickoffReturn", "puntReturn", "pass", "run"], 17, 15,
            pos_odds={"S": 0.35, "CB": 0.15, "LB": 0.4, "DL": 0.1}, automatic_first_down=True, tack_on=True),
    Penalty("Ineligible receiver downfield", "무자격 리시버 전진", "offense", ["pass"], 16, 5, pos_odds={"OL": 1}),
    Penalty("Horse collar tackle", "호스 칼라 태클", "defense", ["kickoffReturn", "puntReturn", "pass", "run"], 14, 15,
            pos_odds={"S": 0.3, "CB": 0.1, "LB": 0.4, "DL": 0.2}, automatic_first_down=True, tack_on=True),
    Penalty("Chop block", "찹 블록", "offense", ["run"], 12, 15, pos_odds={"OL": 0.9, "TE": 0.1}),
    Penalty("Illegal motion", "일리걸 모션", "offense", ["beforeSnap"], 11, 5,
            pos_odds={"RB": 0.2, "WR": 0.6, "TE": 0.2}),
    Penalty("Tripping", "트리핑", "offense", ["kickoffReturn", "puntReturn", "pass", "run"], 5, 10,
            pos_odds={"RB": 0.1, "WR": 0.3, "TE": 0.1, "OL": 0.5}),
    Penalty("Tripping", "트리핑", "defense", ["kickoffReturn", "puntReturn", "pass", "run"], 4, 10,
            pos_odds={"CB": 0.1, "S": 0.2, "LB": 0.3, "DL": 0.4}, automatic_first_down=True, tack_on=True),
    Penalty("Illegal Substitution", "일리걸 서브스티튜션", "offense", ["beforeSnap"], 2, 5, pos_odds={}),
    Penalty("Illegal Substitution", "일리걸 서브스티튜션", "defense", ["beforeSnap"], 6, 5, pos_odds={}),
    Penalty("Ineligible man downfield", "무자격 선수 전진", "offense", ["punt"], 7, 5, pos_odds={"OL": 1}),
    Penalty("Illegal blindside block", "블라인드사이드 블록", "offense", ["run", "pass"], 6, 15,
            pos_odds={"OL": 0.7, "WR": 0.25, "TE": 0.05}),
    Penalty("Leverage", "레버리지", "defense", ["fieldGoal"], 6, 15, pos_odds={"S": 1},
            automatic_first_down=True, tack_on=True),
    Penalty("Illegal touching", "일리걸 터칭", "offense", ["pass"], 4, 5, pos_odds={"OL": 0.95, "WR": 0.05}),
    Penalty("Clipping", "클리핑", "offense", ["pass", "run"], 3, 15, pos_odds={"OL": 0.7, "WR": 0.25, "TE": 0.05}),
    Penalty("Illegal crackback block", "크랙백 블록", "offense", ["pass", "run"], 2, 15, pos_odds={"WR": 1}),
    Penalty("Illegal low block", "로우 블록", "offense", ["pass", "run"], 2, 15,
            pos_odds={"OL": 0.7, "WR": 0.25, "TE": 0.05}),
]

NUM_PLAYS = {"kickoffReturn": 2500, "punt": 2000, "puntReturn": 2000, "fieldGoal": 2000, "pass": 17500, "run": 13000}
NUM_PLAYS["beforeSnap"] = NUM_PLAYS["punt"] + NUM_PLAYS["fieldGoal"] + NUM_PLAYS["pass"] + NUM_PLAYS["run"]

for _pen in PENALTIES:
    _pen.prob_per_play = _pen.num_per_season / sum(NUM_PLAYS[t] for t in _pen.play_types)

# 플레이 유형별 목록 (원래 정의 순서 유지 → 난수 소비 순서 고정)
PENALTIES_BY_PLAY_TYPE: dict[str, list[Penalty]] = {
    t: [p for p in PENALTIES if t in p.play_types] for t in NUM_PLAYS
}
