"""FastAPI 앱. 실행: `gridiron serve` 또는 `uvicorn gridiron.web.app:app`."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..domain.attributes import stars
from . import state, views

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.filters["grade"] = views.grade_class
templates.env.filters["stars"] = lambda pr: "★" * int(stars(pr)) + ("½" if stars(pr) % 1 else "")
templates.env.filters["pct"] = lambda x: "—" if x is None else f"{x * 100:.0f}%"
templates.env.filters["f1"] = lambda x: "—" if x is None else f"{x:.1f}"


def render(request: Request, name: str, ctx: "state.Ctx | None" = None, **data):
    from .jobs import running
    data.update(ctx=ctx, nav=request.url.path, job=running())
    if ctx is not None and ctx.user:
        data.setdefault("top_record", views.record(ctx.league, ctx.user))
        data.setdefault("top_week", views.week_title(ctx.league))
    return templates.TemplateResponse(request, name, data)


def need_ctx(request: Request) -> "state.Ctx":
    ctx = state.current(request)
    if ctx is None:
        raise NoSlot()
    return ctx


class NoSlot(Exception):
    pass


def create_app() -> FastAPI:
    app = FastAPI(title="Gridiron Manager")
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.exception_handler(NoSlot)
    async def _no_slot(request: Request, exc: NoSlot):
        return RedirectResponse("/new", status_code=303)

    from .routes import core
    app.include_router(core.router)
    for mod in ("squad", "tactics", "league"):
        try:
            m = __import__(f"gridiron.web.routes.{mod}", fromlist=["router"])
        except ModuleNotFoundError:
            continue
        app.include_router(m.router)
    return app


app = create_app()
