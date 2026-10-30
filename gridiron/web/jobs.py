"""오래 걸리는 작업(경기 진행, 구단주 투영)을 백그라운드 스레드로 돌리고 HTMX가 진행 상황을 폴링한다."""
from __future__ import annotations

import itertools
import threading
import traceback
from dataclasses import dataclass, field
from typing import Callable

from . import state

_ids = itertools.count(1)
JOBS: dict[int, "Job"] = {}


@dataclass
class Job:
    id: int
    title: str
    redirect: str = "/home"
    lines: list[str] = field(default_factory=list)
    done: bool = False
    error: str | None = None
    progress: float = 0.0          # 0–1 (모르면 0)

    def log(self, line: str, progress: float | None = None) -> None:
        self.lines.append(line)
        if progress is not None:
            self.progress = progress


def running() -> Job | None:
    return next((j for j in JOBS.values() if not j.done), None)


def start(title: str, fn: Callable[[Job], str | None], redirect: str = "/home") -> Job:
    """fn(job)을 스레드에서 실행. fn이 문자열을 돌려주면 끝난 뒤 그 주소로 이동."""
    busy = running()
    if busy:
        return busy
    job = Job(next(_ids), title, redirect)
    JOBS[job.id] = job

    def run() -> None:
        try:
            with state.LOCK:
                target = fn(job)
            if target:
                job.redirect = target
        except Exception as e:  # noqa: BLE001 — 화면에 오류를 보여준다
            job.error = f"{type(e).__name__}: {e}"
            job.lines.append(traceback.format_exc(limit=3))
        finally:
            state.invalidate()
            job.progress = 1.0
            job.done = True

    threading.Thread(target=run, daemon=True).start()
    return job
