"""
Read-only data loading, gh CLI interaction, and tracker file I/O.

Security invariants:
  - subprocess calls use exec (never shell=True)
  - stderr from gh is never forwarded to the client
  - all slug / issue-number / URL inputs are validated before use
  - the server binds to 127.0.0.1 only
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import tomllib

from ..defaults import resolve_tracker

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

# owner__repo — both parts are GitHub-legal (alphanum, hyphen, dot, underscore)
_SLUG_RE = re.compile(r"^[a-zA-Z0-9._-]+__[a-zA-Z0-9._-]+$")
_OWNER_REPO_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")
_ISSUE_URL_RE = re.compile(
    r"^https://github\.com/" r"([a-zA-Z0-9._-]+)/([a-zA-Z0-9._-]+)" r"/issues/(\d+)$"
)
# Reject non-repo github URLs (sponsors, marketplace, settings, etc.)
_NON_REPO_PREFIXES = ("sponsors/", "settings/", "marketplace/", "orgs/")


def _valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug))


def _valid_owner_repo(s: str) -> bool:
    if not _OWNER_REPO_RE.match(s):
        return False
    owner = s.split("/", 1)[0]
    return not any(owner == p.rstrip("/") for p in _NON_REPO_PREFIXES)


def _slug_to_owner_repo(slug: str) -> str | None:
    if not _valid_slug(slug):
        return None
    owner, repo = slug.split("__", 1)
    candidate = f"{owner}/{repo}"
    return candidate if _valid_owner_repo(candidate) else None


def _escape_toml_value(s: str) -> str:
    """Escape a string for TOML double-quoted value."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------------------------------------------------------------------------
# Data store
# ---------------------------------------------------------------------------


class TrackerStore:
    """Holds read-only package data in memory, manages tracker output on disk."""

    def __init__(self, target: Path, name: str | None = None) -> None:
        self.target = target
        self.meta = resolve_tracker(name)
        self.repos_dir = target / self.meta["repos_dir"]
        self.packages_dir = target / self.meta["packages_dir"]
        self.pending_dir = target / self.meta["pending_dir"]
        self.keywords: list[str] = self.meta["keywords"]
        self._load_sources()

    # -- read-only source data ---------------------------------------------

    def _load_sources(self) -> None:
        parquet_path = self.target / self.meta["source"]
        report_path = self.target / self.meta["report"]

        parquet = pl.read_parquet(parquet_path, columns=["name", "github_url"])
        report = pl.read_csv(report_path, separator="\t")

        self.df = (
            report.join(parquet, on="name", how="left")
            .with_columns(
                pl.when(
                    pl.col("github_url").is_not_null()
                    & ~pl.col("github_url").str.contains("sponsors/")
                )
                .then(
                    pl.col("github_url")
                    .str.replace("https://github.com/", "")
                    .str.replace("/", "__")
                )
                .otherwise(pl.lit(None))
                .alias("slug")
            )
            .sort("rank")
        )

    def search_packages(
        self,
        query: str,
        limit: int = 40,
        offset: int = 0,
        hide_tp: bool = True,
        tracked_only: bool = False,
    ) -> list[dict]:
        tracked = self.tracked_slugs()

        filtered = self.df
        q = query.strip().lower()
        if q:
            filtered = filtered.filter(pl.col("name").str.contains(q, literal=True))

        if hide_tp:
            filtered = filtered.filter(pl.col("verdict") != "tp")

        if tracked_only:
            tracked_list = list(tracked)
            if not tracked_list:
                return []
            filtered = filtered.filter(pl.col("slug").is_in(tracked_list))

        results = filtered.slice(offset, limit).to_dicts()
        for row in results:
            row["is_tracked"] = row.get("slug") in tracked
        return results

    def get_repo_packages(self, slug: str) -> list[dict]:
        if not _valid_slug(slug):
            return []
        return self.df.filter(pl.col("slug") == slug).sort("rank").to_dicts()

    def github_url_for_slug(self, slug: str) -> str | None:
        owner_repo = _slug_to_owner_repo(slug)
        return f"https://github.com/{owner_repo}" if owner_repo else None

    # -- tracker output on disk --------------------------------------------

    def read_tracked(self, slug: str) -> list[dict]:
        if not _valid_slug(slug):
            return []
        repo_dir = self.repos_dir / slug
        if not repo_dir.exists():
            return []
        tracked = []
        for f in sorted(repo_dir.glob("*.toml")):
            try:
                data = tomllib.loads(f.read_text())
                data["number"] = int(f.stem)
                tracked.append(data)
            except (ValueError, tomllib.TOMLDecodeError):
                continue
        return tracked

    def write_tracked(
        self,
        slug: str,
        number: int,
        issue_url: str,
        title: str,
        state: str,
        keyword: str = "",
    ) -> Path:
        if not _valid_slug(slug):
            raise ValueError(f"Invalid slug: {slug!r}")
        if number <= 0:
            raise ValueError(f"Invalid issue number: {number}")

        repo_dir = self.repos_dir / slug
        repo_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            f'issue_url = "{_escape_toml_value(issue_url)}"',
            f'title = "{_escape_toml_value(title)}"',
            f'state = "{_escape_toml_value(state)}"',
            f'keyword = "{_escape_toml_value(keyword)}"',
            f'tracked_at = "{now}"',
        ]
        path = repo_dir / f"{number}.toml"
        path.write_text("\n".join(lines) + "\n")

        self._ensure_symlinks(slug)
        return path

    def _ensure_symlinks(self, slug: str) -> None:
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        names = self.df.filter(pl.col("slug") == slug)["name"].to_list()
        rel = Path("../repos") / slug
        for name in names:
            link = self.packages_dir / name
            if link.is_symlink() or link.exists():
                continue
            link.symlink_to(rel)

    def get_status(self) -> dict:
        if not self.repos_dir.exists():
            return {"repos_tracked": 0, "issues_tracked": 0, "packages_covered": 0}
        repos = [d for d in self.repos_dir.iterdir() if d.is_dir()]
        slugs_with_issues = {d.name for d in repos if any(d.glob("*.toml"))}
        issues = sum(len(list(d.glob("*.toml"))) for d in repos)
        packages = self.df.filter(pl.col("slug").is_in(list(slugs_with_issues))).height
        total_notp = self.df.filter(pl.col("verdict") == "notp").height
        return {
            "repos_tracked": len(slugs_with_issues),
            "issues_tracked": issues,
            "packages_covered": packages,
            "total_packages": self.df.height,
            "total_notp": total_notp,
        }

    def tracked_slugs(self) -> set[str]:
        """Return the set of slugs that have at least one tracked issue."""
        if not self.repos_dir.exists():
            return set()
        return {
            d.name
            for d in self.repos_dir.iterdir()
            if d.is_dir() and any(d.glob("*.toml"))
        }

    # -- pending / triage -----------------------------------------------------

    def read_pending(self, slug: str) -> list[dict]:
        """Read all pending issues for a given repo slug."""
        if not _valid_slug(slug):
            return []
        repo_dir = self.pending_dir / slug
        if not repo_dir.exists():
            return []
        pending = []
        for f in sorted(repo_dir.glob("*.toml")):
            try:
                data = tomllib.loads(f.read_text())
                data["number"] = int(f.stem)
                pending.append(data)
            except (ValueError, tomllib.TOMLDecodeError):
                continue
        return pending

    def list_pending_repos(
        self,
        limit: int = 40,
        offset: int = 0,
    ) -> list[dict]:
        """Return pending repos with their issues and package info."""
        if not self.pending_dir.exists():
            return []

        repos = []
        for d in sorted(self.pending_dir.iterdir()):
            if not d.is_dir():
                continue
            toml_files = list(d.glob("*.toml"))
            if not toml_files:
                continue
            slug = d.name
            owner_repo = _slug_to_owner_repo(slug)
            if not owner_repo:
                continue

            issues = []
            for f in sorted(toml_files):
                try:
                    data = tomllib.loads(f.read_text())
                    data["number"] = int(f.stem)
                    issues.append(data)
                except (ValueError, tomllib.TOMLDecodeError):
                    continue

            packages = self.get_repo_packages(slug)
            repos.append({
                "slug": slug,
                "owner_repo": owner_repo,
                "issues": issues,
                "packages": packages,
                "issue_count": len(issues),
            })

        return repos[offset : offset + limit]

    def accept_pending(
        self,
        slug: str,
        number: int,
    ) -> Path:
        """Move a pending issue to tracked (accept it)."""
        if not _valid_slug(slug):
            raise ValueError(f"Invalid slug: {slug!r}")

        pending_path = self.pending_dir / slug / f"{number}.toml"
        if not pending_path.exists():
            raise ValueError(f"No pending issue #{number} for {slug}")

        data = tomllib.loads(pending_path.read_text())

        # Write as tracked (reusing write_tracked for symlink management)
        result = self.write_tracked(
            slug,
            number,
            data.get("issue_url", ""),
            data.get("title", ""),
            data.get("state", ""),
            data.get("keyword", ""),
        )

        # Remove pending file
        pending_path.unlink()
        # Clean up empty pending dir
        parent = pending_path.parent
        if parent.exists() and not any(parent.glob("*.toml")):
            parent.rmdir()

        return result

    def dismiss_pending(self, slug: str, number: int) -> None:
        """Dismiss (delete) a pending issue without tracking it."""
        if not _valid_slug(slug):
            raise ValueError(f"Invalid slug: {slug!r}")

        pending_path = self.pending_dir / slug / f"{number}.toml"
        if not pending_path.exists():
            raise ValueError(f"No pending issue #{number} for {slug}")

        pending_path.unlink()
        # Clean up empty pending dir
        parent = pending_path.parent
        if parent.exists() and not any(parent.glob("*.toml")):
            parent.rmdir()

    def dismiss_all_pending(self, slug: str) -> int:
        """Dismiss all pending issues for a repo. Returns count dismissed."""
        if not _valid_slug(slug):
            raise ValueError(f"Invalid slug: {slug!r}")

        repo_dir = self.pending_dir / slug
        if not repo_dir.exists():
            return 0

        count = 0
        for f in list(repo_dir.glob("*.toml")):
            f.unlink()
            count += 1

        if repo_dir.exists() and not any(repo_dir.iterdir()):
            repo_dir.rmdir()

        return count

    def get_pending_status(self) -> dict:
        """Return summary stats for pending items."""
        if not self.pending_dir.exists():
            return {"pending_repos": 0, "pending_issues": 0}
        repos = [d for d in self.pending_dir.iterdir() if d.is_dir()]
        pending_repos = 0
        pending_issues = 0
        for d in repos:
            tomls = list(d.glob("*.toml"))
            if tomls:
                pending_repos += 1
                pending_issues += len(tomls)
        return {"pending_repos": pending_repos, "pending_issues": pending_issues}


# ---------------------------------------------------------------------------
# gh CLI wrappers (async, never shell=True, stderr never exposed)
# ---------------------------------------------------------------------------


async def check_gh_auth() -> bool:
    """Return True if the gh CLI is installed and authenticated."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "auth",
            "status",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
    except FileNotFoundError:
        return False


async def gh_search_issues(owner_repo: str, keywords: list[str]) -> list[dict]:
    """Search a repo's issues for any of the given keywords. Deduplicates."""
    if not _valid_owner_repo(owner_repo):
        raise ValueError(f"Invalid owner/repo: {owner_repo!r}")

    seen: dict[int, dict] = {}
    for kw in keywords:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "issue",
            "list",
            "-R",
            owner_repo,
            "--search",
            kw,
            "--json",
            "number,title,url,state,createdAt",
            "--limit",
            "20",
            "--state",
            "all",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            # stderr may contain auth details — do not forward
            raise RuntimeError(f"gh issue list failed (exit {proc.returncode})")
        for issue in json.loads(stdout):
            if issue["number"] not in seen:
                issue["keyword"] = kw
                seen[issue["number"]] = issue

    return sorted(seen.values(), key=lambda x: x["number"], reverse=True)


async def gh_view_issue(issue_url: str) -> dict:
    """Fetch metadata for a single issue by its full URL."""
    if not _ISSUE_URL_RE.match(issue_url):
        raise ValueError(f"Invalid issue URL: {issue_url!r}")

    proc = await asyncio.create_subprocess_exec(
        "gh",
        "issue",
        "view",
        issue_url,
        "--json",
        "number,title,url,state,createdAt",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"gh issue view failed (exit {proc.returncode})")
    return json.loads(stdout)
