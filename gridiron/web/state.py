"""세이브 슬롯과 현재 리그 (한 사람용 로컬 앱).

슬롯 = saves/<이름>.sqlite. 현재 슬롯은 쿠키 `slot`. 리그는 파일 수정 시각이 같으면 메모리에 둔 것을 다시 쓴다.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from ..domain.models import League

_cache: dict[Path, tuple[int, League, str | None]] = {}
LOCK = threading.RLock()          # 리그를 바꾸는 작업은 한 번에 하나


def saves_dir() -> Path:
    d = Path(os.environ.get("GRIDIRON_SAVES", "saves"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def slot_path(name: str) -> Path:
    if not re.fullmatch(r"[\w\-가-힣]{1,40}", name or ""):
        raise ValueError("슬롯 이름은 글자·숫자·_·- 40자 이내")
    return saves_dir() / f"{name}.sqlite"


def slots() -> list[dict]:
    from sqlmodel import Session, select

    from ..db import schema as S
    from ..db.store import engine_for
    out = []
    for p in sorted(saves_dir().glob("*.sqlite"), key=lambda x: -x.stat().st_mtime):
        try:
            with Session(engine_for(p)) as s:
                m = s.exec(select(S.LeagueRow)).one()
            out.append({"name": p.stem, "season": m.season, "week": m.week, "phase": m.phase, "team": m.user_team,
                        "source": m.source, "ok": m.schema_version == S.SCHEMA_VERSION})
        except Exception:  # noqa: BLE001 — 깨진 파일은 목록에서 표시만
            out.append({"name": p.stem, "ok": False})
    return out


def load(path: Path) -> tuple[League, str | None]:
    from ..db.store import load_league
    with LOCK:
        mt = path.stat().st_mtime_ns
        hit = _cache.get(path)
        if hit and hit[0] == mt:
            return hit[1], hit[2]
        league, user = load_league(path)
        _cache[path] = (path.stat().st_mtime_ns, league, user)
        return league, user


def invalidate(path: Path | None = None) -> None:
    with LOCK:
        if path is None:
            _cache.clear()
        else:
            _cache.pop(path, None)


@dataclass
class Ctx:
    name: str
    path: Path
    league: League
    user: str | None

    @property
    def team(self):
        return self.league.teams[self.user] if self.user else None


def current(request: Request) -> Ctx | None:
    name = request.cookies.get("slot")
    if not name:
        return None
    try:
        path = slot_path(name)
    except ValueError:
        return None
    if not path.exists():
        return None
    league, user = load(path)
    return Ctx(name, path, league, user)
