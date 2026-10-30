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
