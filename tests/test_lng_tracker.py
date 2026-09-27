"""원본 LngTracker.test.ts 포팅."""
from gridiron.engine.skeleton.lng_tracker import LngTracker


def test_works():
    t = LngTracker()
    assert t.log("player", 4, "foo", 6) == 6
    assert t.log("player", 4, "foo", 16) == 16
    assert t.log("player", 4, "foo", 10, True) == 16
    assert t.log("player", 4, "foo", 16, True) == 6


def test_negative_values():
    t = LngTracker()
    assert t.log("player", 4, "foo", -6) == -6
    assert t.log("player", 4, "foo", -1) == -1
    assert t.log("player", 4, "foo", -3, True) == -1
    assert t.log("player", 4, "foo", -1, True) == -6
