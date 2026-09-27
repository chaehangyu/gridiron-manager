"""포지션 정의.

선수의 주 포지션(`Position`)과 뎁스차트 슬롯(`Slot`)을 구분한다.
- 주 포지션: 선수가 원래 뛰는 자리 (예: OT, EDGE)
- 슬롯: 뎁스차트에서 실제로 서는 자리 (예: LT, RT, LDE, NB)

엔진 골격(Football GM 포팅)은 더 굵은 단위의 "엔진 포지션"(QB, RB, WR, TE, OL, DL, LB, CB, S, K, P, KR, PR)을 쓴다.
"""
from __future__ import annotations

from enum import Enum


class Position(str, Enum):
    QB = "QB"
    RB = "RB"
    FB = "FB"
    WR = "WR"
    TE = "TE"
    OT = "OT"
    OG = "OG"
    C = "C"
    EDGE = "EDGE"
    DT = "DT"
    LB = "LB"
    CB = "CB"
    S = "S"
    K = "K"
    P = "P"
    LS = "LS"


POSITION_LABEL_KO = {
    Position.QB: "쿼터백",
    Position.RB: "러닝백",
    Position.FB: "풀백",
    Position.WR: "와이드 리시버",
    Position.TE: "타이트 엔드",
    Position.OT: "오펜시브 태클",
    Position.OG: "오펜시브 가드",
    Position.C: "센터",
    Position.EDGE: "엣지 러셔",
    Position.DT: "디펜시브 태클",
    Position.LB: "라인배커",
    Position.CB: "코너백",
    Position.S: "세이프티",
    Position.K: "키커",
    Position.P: "펀터",
    Position.LS: "롱 스내퍼",
}

OFFENSE = {Position.QB, Position.RB, Position.FB, Position.WR, Position.TE, Position.OT, Position.OG, Position.C}
DEFENSE = {Position.EDGE, Position.DT, Position.LB, Position.CB, Position.S}
SPECIAL = {Position.K, Position.P, Position.LS}


class Front(str, Enum):
    """수비 기본 프론트."""

    FOUR_THREE = "4-3"
    THREE_FOUR = "3-4"


# 뎁스차트 슬롯. 값은 (유닛, 슬롯 이름).
OFFENSE_SLOTS = ["QB", "RB", "FB", "WR_X", "WR_Z", "WR_SLOT", "TE", "LT", "LG", "C", "RG", "RT"]
DEFENSE_SLOTS_43 = ["LDE", "LDT", "RDT", "RDE", "WLB", "MLB", "SLB", "LCB", "RCB", "NB", "FS", "SS"]
DEFENSE_SLOTS_34 = ["LDE", "NT", "RDE", "WOLB", "LILB", "RILB", "SOLB", "LCB", "RCB", "NB", "FS", "SS"]
SPECIAL_SLOTS = ["K", "P", "LS", "H", "KR", "PR"]

# 슬롯이 요구하는 기본 포지션 (자동 뎁스차트와 적합성 경고에 사용)
SLOT_POSITIONS: dict[str, tuple[Position, ...]] = {
    "QB": (Position.QB,),
    "RB": (Position.RB,),
    "FB": (Position.FB, Position.RB, Position.TE),
    "WR_X": (Position.WR,),
    "WR_Z": (Position.WR,),
    "WR_SLOT": (Position.WR,),
    "TE": (Position.TE,),
    "LT": (Position.OT,),
    "RT": (Position.OT,),
    "LG": (Position.OG,),
    "RG": (Position.OG,),
    "C": (Position.C, Position.OG),
    "LDE": (Position.EDGE, Position.DT),
    "RDE": (Position.EDGE, Position.DT),
    "LDT": (Position.DT,),
    "RDT": (Position.DT,),
    "NT": (Position.DT,),
    "WOLB": (Position.EDGE, Position.LB),
    "SOLB": (Position.EDGE, Position.LB),
    "WLB": (Position.LB,),
    "MLB": (Position.LB,),
    "SLB": (Position.LB,),
    "LILB": (Position.LB,),
    "RILB": (Position.LB,),
    "LCB": (Position.CB,),
    "RCB": (Position.CB,),
    "NB": (Position.CB, Position.S),
    "FS": (Position.S,),
    "SS": (Position.S,),
    "K": (Position.K,),
    "P": (Position.P,),
    "LS": (Position.LS,),
    "H": (Position.P, Position.QB, Position.K),
    "KR": (Position.WR, Position.RB, Position.CB),
    "PR": (Position.WR, Position.CB, Position.RB),
}


def defense_slots(front: Front) -> list[str]:
    return DEFENSE_SLOTS_43 if front == Front.FOUR_THREE else DEFENSE_SLOTS_34


def all_slots(front: Front) -> list[str]:
    return OFFENSE_SLOTS + defense_slots(front) + SPECIAL_SLOTS


# ── 엔진 포지션 (Football GM 골격이 쓰는 단위) ──────────────────────────────
ENGINE_POSITIONS = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "CB", "S", "K", "P", "KR", "PR"]

# 수비 슬롯 → 엔진 포지션. 3-4의 OLB는 패스 러셔이므로 DL로 본다.
DEFENSE_SLOT_TO_ENGINE = {
    "LDE": "DL", "RDE": "DL", "LDT": "DL", "RDT": "DL", "NT": "DL",
    "WOLB": "DL", "SOLB": "DL",
    "WLB": "LB", "MLB": "LB", "SLB": "LB", "LILB": "LB", "RILB": "LB",
    "LCB": "CB", "RCB": "CB", "NB": "CB",
    "FS": "S", "SS": "S",
}
OFFENSE_SLOT_TO_ENGINE = {
    "QB": "QB", "RB": "RB", "FB": "RB",
    "WR_X": "WR", "WR_Z": "WR", "WR_SLOT": "WR",
    "TE": "TE",
    "LT": "OL", "LG": "OL", "C": "OL", "RG": "OL", "RT": "OL",
}
SPECIAL_SLOT_TO_ENGINE = {"K": "K", "P": "P", "KR": "KR", "PR": "PR"}

# 주 포지션 → 엔진 포지션 (뎁스차트에 없는 백업을 채울 때)
POSITION_TO_ENGINE = {
    Position.QB: "QB", Position.RB: "RB", Position.FB: "RB", Position.WR: "WR", Position.TE: "TE",
    Position.OT: "OL", Position.OG: "OL", Position.C: "OL",
    Position.EDGE: "DL", Position.DT: "DL", Position.LB: "LB", Position.CB: "CB", Position.S: "S",
    Position.K: "K", Position.P: "P", Position.LS: "OL",
}
