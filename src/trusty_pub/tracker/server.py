"""FastAPI application — all endpoints return HTML fragments for htmx."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .store import (
    _ISSUE_URL_RE,
    TrackerStore,
    _slug_to_owner_repo,
    check_gh_auth,
    gh_search_issues,
    gh_view_issue,
)

_HERE = Path(__file__).parent
_PAGE_SIZE = 40


def create_app(target: Path) -> FastAPI:
    app = FastAPI(title="Trusty Pub Tracker")
    store = TrackerStore(target)

    templates = Jinja2Templates(directory=str(_HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

    templates.env.globals["slug_to_owner_repo"] = _slug_to_owner_repo

    def _repo_context(slug: str, **extra) -> dict:
        return {
            "slug": slug,
            "packages": store.get_repo_packages(slug),
            "tracked": store.read_tracked(slug),
            "github_url": store.github_url_for_slug(slug),
            "keywords": store.keywords,
            **extra,
        }

    def _repo_detail_response(request: Request, slug: str, flash: str | None = None):
        ctx = _repo_context(slug, flash=flash) if flash else _repo_context(slug)
        response = templates.TemplateResponse(
            request, "fragments/repo_detail.html", ctx
        )
        if flash:
            response.headers["HX-Trigger"] = "trackUpdate"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        gh_ok = await check_gh_auth()
        status = store.get_status()
        return templates.TemplateResponse(
            request, "index.html", {"gh_ok": gh_ok, "status": status}
        )

    @app.get("/search", response_class=HTMLResponse)
    async def search(
        request: Request,
        q: str = Query(""),
        hide_tp: str = Query(""),
        tracked_only: str = Query(""),
        offset: int = Query(0),
    ):
        results = store.search_packages(
            q,
            limit=_PAGE_SIZE,
            offset=offset,
            hide_tp=hide_tp == "on",
            tracked_only=tracked_only == "on",
        )
        has_more = len(results) == _PAGE_SIZE
        next_offset = offset + _PAGE_SIZE
        template = (
            "fragments/search.html" if offset == 0 else "fragments/search_more.html"
        )
        return templates.TemplateResponse(
            request,
            template,
            {
                "results": results,
                "has_more": has_more,
                "next_offset": next_offset,
            },
        )

    @app.get("/repo/{slug}", response_class=HTMLResponse)
    async def repo_detail(request: Request, slug: str):
        packages = store.get_repo_packages(slug)
        if not packages:
            return HTMLResponse("<p>Unknown repo</p>", status_code=404)
        return _repo_detail_response(request, slug)

    @app.post("/issues", response_class=HTMLResponse)
    async def search_issues(request: Request, slug: str = Form(...)):
        owner_repo = _slug_to_owner_repo(slug)
        if not owner_repo:
            return HTMLResponse("<p>Invalid repo</p>", status_code=400)
        try:
            issues = await gh_search_issues(owner_repo, store.keywords)
        except RuntimeError:
            return HTMLResponse(
                "<p class='error'>gh CLI error — check terminal</p>",
                status_code=502,
            )
        already = {t["number"] for t in store.read_tracked(slug)}
        return templates.TemplateResponse(
            request,
            "fragments/issues.html",
            {"slug": slug, "issues": issues, "already_tracked": already},
        )

    @app.post("/track", response_class=HTMLResponse)
    async def track(
        request: Request,
        slug: str = Form(...),
        number: int = Form(...),
        url: str = Form(...),
        title: str = Form(...),
        state: str = Form(...),
        keyword: str = Form(""),
    ):
        try:
            store.write_tracked(slug, number, url, title, state, keyword)
        except ValueError as exc:
            return HTMLResponse(f"<p class='error'>{exc}</p>", status_code=400)
        return _repo_detail_response(request, slug, flash=f"Tracked #{number}")

    @app.post("/paste", response_class=HTMLResponse)
    async def paste_url(request: Request, url: str = Form(...)):
        url = url.strip()
        m = _ISSUE_URL_RE.match(url)
        if not m:
            return HTMLResponse(
                "<p class='error'>Not a valid GitHub issue URL</p>",
                status_code=400,
            )
        owner, repo, number_str = m.groups()
        slug = f"{owner}__{repo}"
        owner_repo = f"{owner}/{repo}"

        packages = store.get_repo_packages(slug)
        if not packages:
            return HTMLResponse(
                f"<p class='error'>Repo {owner_repo} not in dataset</p>",
                status_code=404,
            )

        try:
            issue = await gh_view_issue(url)
        except RuntimeError:
            return HTMLResponse(
                "<p class='error'>gh CLI error — check terminal</p>",
                status_code=502,
            )

        store.write_tracked(
            slug,
            issue["number"],
            issue["url"],
            issue["title"],
            issue["state"],
        )
        return _repo_detail_response(
            request, slug, flash=f"Tracked #{issue['number']}"
        )

    @app.get("/status", response_class=HTMLResponse)
    async def status(request: Request):
        s = store.get_status()
        return templates.TemplateResponse(
            request, "fragments/status.html", {"status": s}
        )

    return app