"""원본 penalties.test.ts 포팅 + 확률 계산 확인."""
from gridiron.engine.skeleton.penalties import PENALTIES, PENALTIES_BY_PLAY_TYPE


def test_pos_odds_sum_to_one():
    for pen in PENALTIES:
        if not pen.pos_odds:
            continue
        total = sum(pen.pos_odds.values())
        assert 0.999 < total < 1.001, f"{pen.name} ({pen.side}) posOdds 합 {total}"


def test_prob_per_play_positive_and_small():
    for pen in PENALTIES:
        assert 0 < pen.prob_per_play < 0.1  # 펀트 리턴 백 블록이 리턴당 약 9%로 가장 높다


def test_by_play_type_keeps_definition_order():
    names = [p.name for p in PENALTIES_BY_PLAY_TYPE["beforeSnap"]]
    assert names[0] == "False start"
