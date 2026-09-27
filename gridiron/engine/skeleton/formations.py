"""포메이션 (원본 formations.ts). M4에서 퍼스넬 패키지(F3-5)로 대체한다."""

NORMAL = [
    {"off": {"QB": 1, "RB": 1, "WR": 3, "TE": 1, "OL": 5}, "def": {"DL": 4, "LB": 2, "CB": 3, "S": 2}},
    {"off": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "OL": 5}, "def": {"DL": 3, "LB": 4, "CB": 2, "S": 2}},
    {"off": {"QB": 1, "RB": 2, "WR": 1, "TE": 2, "OL": 5}, "def": {"DL": 4, "LB": 3, "CB": 2, "S": 2}},
]
FIELD_GOAL = [{"off": {"K": 1, "P": 1, "OL": 9}, "def": {"DL": 6, "LB": 3, "S": 2}}]
KICKOFF = [{"off": {"K": 1, "LB": 5, "S": 3, "CB": 2}, "def": {"KR": 2, "LB": 5, "S": 4}}]
PUNT = [{"off": {"P": 1, "RB": 1, "OL": 7, "CB": 2}, "def": {"PR": 1, "DL": 6, "S": 4}}]
