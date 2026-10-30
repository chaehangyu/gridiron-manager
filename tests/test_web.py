"""웹 UI (M6): 화면별 응답과 진행 흐름. 샘플 리그로 빠르게 검사한다."""
import re
import time

import pytest
from fastapi.testclient import TestClient


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def wait_job(c, loc: str, timeout: float = 600) -> str:
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(loc, headers={"HX-Request": "true"})
        if "HX-Redirect" in r.headers:
            return r.headers["HX-Redirect"]
        assert "오류" not in r.text, r.text[-1500:]
        time.sleep(0.2)
    raise AssertionError("작업이 끝나지 않음")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os
    os.environ["GRIDIRON_SAVES"] = str(tmp_path_factory.mktemp("saves"))
    from gridiron.web.app import app
    c = TestClient(app)
    r = c.post("/new", data={"team": "S01", "slot": "web_test", "source": "sample"}, follow_redirects=False)
    assert r.status_code == 303
    assert wait_job(c, r.headers["location"]) == "/home"
    return c


def test_new_game_and_home(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/home"
    r = client.get("/home")
    assert r.status_code == 200
    t = _text(r.text)
    assert "이번 주 할 일" in t and "인박스" in t and "디비전 순위" in t
    slots = _text(client.get("/new").text)
    assert "web_test" in slots


def test_play_week_updates_home(client):
    r = client.post("/play/week", follow_redirects=False)
    assert wait_job(client, r.headers["location"]) == "/home"
    t = _text(client.get("/home").text)
    assert "2주차" in t and ("승" in t or "패" in t or "바이" in t)


def test_settings_roundtrip(client):
    r = client.post("/settings", data={"firing": "off", "auto_roster": "on", "injury_risk": "conservative"},
                    follow_redirects=True)
    assert "저장했습니다" in r.text and 'value="conservative" selected' in r.text


def test_no_slot_redirects_to_new(tmp_path):
    from gridiron.web.app import app
    c = TestClient(app)
    assert c.get("/home", follow_redirects=False).headers["location"] == "/new"


def test_squad_pages(client):
    for url in ("/roster", "/roster?tab=ps", "/roster?tab=ir", "/roster?tab=fa&pos=WR", "/roster?team=S02",
                "/depth", "/depth?unit=defense", "/depth?unit=special", "/injuries"):
        r = client.get(url)
        assert r.status_code == 200, url
    pid = re.search(r'/player/([^"]+)"', client.get("/roster?team=S02").text).group(1)
    t = _text(client.get(f"/player/{pid}").text)
    assert "능력치" in t and "포지션별 PR" in t and "비공개" in t       # 다른 팀 선수: 범위·숨김 비공개


def test_roster_actions(client):
    fa = re.search(r'/roster/sign_ps/([^"]+)"', client.get("/roster?tab=fa").text).group(1)
    r = client.post(f"/roster/sign_ps/{fa}", data={"back": "/roster?tab=ps"}, follow_redirects=True)
    assert "연습 스쿼드 영입" in r.text or "가득" in r.text
    r = client.post(f"/roster/release/{fa}", data={"back": "/roster?tab=ps"}, follow_redirects=True)
    assert r.status_code == 200


def test_depth_save_and_auto(client):
    html = client.get("/depth").text
    ids = re.findall(r'data-slot="QB">\s*<div class="dragitem" data-id="([^"]+)"', html)
    assert ids
    r = client.post("/depth", json={"QB": list(reversed(re.findall(
        r'data-id="([^"]+)"', html.split('data-slot="QB"')[1].split('data-slot=')[0])))})
    assert r.json()["ok"]
    r = client.post("/depth/auto", data={"unit": "offense"}, follow_redirects=True)
    assert "자동 편성 완료" in r.text


def test_coaching_pages(client):
    for url in ("/tactics", "/gameplan", "/training", "/scout"):
        assert client.get(url).status_code == 200, url
    r = client.post("/tactics/preview", data={"offense.run_share": "0.6", "offense.run_style": "gap",
                                              "defense.blitz": "2.5"})
    assert "팀 궁합" in r.text and "노출도" in r.text


def test_tactics_save_preset_and_validation(client):
    r = client.post("/tactics/preset", data={"off": "west_coast", "def": "tampa2"}, follow_redirects=True)
    assert "west_coast+tampa2" in r.text
    r = client.post("/tactics", data={"name": "custom", "offense.run_share": "0.95"}, follow_redirects=True)
    assert "런 비율은" in r.text                                        # 검증 오류 표시
    r = client.post("/tactics", data={"name": "mine", "offense.run_share": "0.5", "offense.run_style": "gap",
                                      "sit.3l|opp.pass": "0.2", "sit.3l|opp.blitz": "1.5"}, follow_redirects=True)
    assert "저장했습니다" in r.text and 'value="0.2"' in r.text


def test_gameplan_training_scout_save(client):
    r = client.post("/gameplan", data={"use.defense.blitz": "1", "defense.blitz": "1.8"}, follow_redirects=True)
    assert "적용 중" in r.text
    r = client.post("/gameplan", data={"clear": "1"}, follow_redirects=True)
    assert "지웠습니다" in r.text
    r = client.post("/training", data={"main": "familiarity", "main_dom": "cov_zone", "sub": "recovery",
                                       "intensity": "hard"}, follow_redirects=True)
    assert "저장했습니다" in r.text and 'value="hard" selected' in r.text
    r = client.post("/scout", data={"s0": "next_opponent", "s1": "free_agents", "s2": "pos:WR"}, follow_redirects=True)
    assert 'value="pos:WR" selected' in r.text
