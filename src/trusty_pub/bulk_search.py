"""
Bulk search for trusted-publishing tracking issues across untracked repos.

Iterates through repos that don't yet have tracked issues, searches their
GitHub issues via ``gh`` CLI (authenticated), and stores matches in a
``pending/`` holding area for manual triage rather than auto-tracking them.

Usage::

    tp-bulk-search              # search all untracked repos
    tp-bulk-search --limit 50   # cap at 50 repos per run
    tp-bulk-search --verdict notp  # only search repos with notp verdict
    tp-bulk-search --resume     # skip repos already in pending/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .defaults import resolve_bulk_search, resolve_tracker
from .tracker.store import (
    _SLUG_RE,
    _escape_toml_value,
    _slug_to_owner_repo,
    _valid_owner_repo,
)


# ---------------------------------------------------------------------------
# gh helpers (async / concurrent)


async def _gh_search_one(owner_repo: str, kw: str, max_issues: int) -> list[dict]:
    """Search a single keyword in a repo using the gh CLI."""
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
        str(max_issues),
        "--state",
        "all",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        # Might be a private repo, archived, or rate-limited
        return []
    try:
        return json.loads(stdout)
    except Exception:
        return []


async def _gh_search_issues(
    owner_repo: str,
    keywords: list[str],
    max_issues: int = 10,
) -> list[dict]:
    """Concurrent keyword search + dedup.

    Returns a list of issues with keyword annotation, sorted by issue number descending.
    """
    if not _valid_owner_repo(owner_repo):
        return []

    # Launch all keyword searches concurrently
    results = await asyncio.gather(
        *[_gh_search_one(owner_repo, kw, max_issues) for kw in keywords]
    )

    seen: dict[int, dict] = {}
    for kw, issues in zip(keywords, results):
        for issue in issues:
            if issue["number"] not in seen:
                issue["keyword"] = kw
                seen[issue["number"]] = issue

    return sorted(seen.values(), key=lambda x: x["number"], reverse=True)


# ---------------------------------------------------------------------------


def _write_pending(
    pending_dir: Path,
    slug: str,
    issue: dict,
) -> Path:
    """Write a single pending issue TOML file."""
    repo_dir = pending_dir / slug
    repo_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f'issue_url = "{_escape_toml_value(issue["url"])}"',
        f'title = "{_escape_toml_value(issue["title"])}"',
        f'state = "{_escape_toml_value(issue["state"])}"',
        f'keyword = "{_escape_toml_value(issue["keyword"])}"',
        f'found_at = "{now}"',
    ]
    path = repo_dir / f"{issue['number']}.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def _get_untracked_slugs(
    target: Path,
    tracker_meta: dict,
    verdict_filter: str | None = None,
) -> list[tuple[str, str]]:
    """Return (slug, owner/repo) pairs for repos not yet tracked or pending."""
    parquet_path = target / tracker_meta["source"]
    report_path = target / tracker_meta["report"]
    repos_dir = target / tracker_meta["repos_dir"]
    pending_dir = target / tracker_meta["pending_dir"]

    parquet = pl.read_parquet(parquet_path, columns=["name", "github_url"])
    report = pl.read_csv(report_path, separator="\t")

    df = (
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
        .filter(pl.col("slug").is_not_null())
    )

    if verdict_filter:
        df = df.filter(pl.col("verdict") == verdict_filter)

    # Deduplicate to unique slugs (multiple packages can share a repo)
    slugs = df.select("slug").unique().to_series().to_list()

    # Exclude already-tracked repos
    tracked = set()
    if repos_dir.exists():
        tracked = {
            d.name
            for d in repos_dir.iterdir()
            if d.is_dir() and any(d.glob("*.toml"))
        }

    # Exclude already-pending repos
    pending = set()
    if pending_dir.exists():
        pending = {
            d.name
            for d in pending_dir.iterdir()
            if d.is_dir() and any(d.glob("*.toml"))
        }

    result = []
    for slug in sorted(slugs):
        if slug in tracked or slug in pending:
            continue
        if not _SLUG_RE.match(slug):
            continue
        owner_repo = _slug_to_owner_repo(slug)
        if owner_repo:
            result.append((slug, owner_repo))

    return result


# ---------------------------------------------------------------------------


async def _run_bulk_search(
    target: Path,
    limit: int | None = None,
    verdict_filter: str | None = None,
    resume: bool = True,
) -> dict:
    """Run the bulk search and return summary stats."""
    tracker_meta = resolve_tracker()
    bulk_meta = resolve_bulk_search()

    pending_dir = target / tracker_meta["pending_dir"]
    max_issues: int = bulk_meta["max_issues_per_repo"]

    # 🔑 concurrency control
    concurrency: int = bulk_meta.get("concurrency", 15)
    sem = asyncio.Semaphore(concurrency)

    # Combine primary + secondary keywords for search
    all_keywords: list[str] = (
        bulk_meta["primary_keywords"] + bulk_meta["secondary_keywords"]
    )

    candidates = _get_untracked_slugs(target, tracker_meta, verdict_filter)
    if limit:
        candidates = candidates[:limit]

    total = len(candidates)
    print(f"Bulk searching {total} untracked repos (concurrency={concurrency})...")

    repos_with_hits = 0
    issues_found = 0
    errors = 0

    async def process_repo(idx: int, slug: str, owner_repo: str):
        nonlocal repos_with_hits, issues_found, errors

        prefix = f"[{idx}/{total}]"

        # Skip if already pending (for resume mode)
        if resume and (pending_dir / slug).exists():
            print(f"{prefix} {owner_repo} — already pending, skipping")
            return

        async with sem:
            try:
                issues = await _gh_search_issues(
                    owner_repo, all_keywords, max_issues
                )
            except Exception:
                errors += 1
                print(f"{prefix} {owner_repo} — error")
                return

            if issues:
                repos_with_hits += 1
                for issue in issues:
                    _write_pending(pending_dir, slug, issue)
                    issues_found += 1
                print(f"{prefix} {owner_repo} — {len(issues)} issue(s)")
            else:
                print(f"{prefix} {owner_repo} — no issues")

    # Launch all repo searches concurrently
    await asyncio.gather(
        *[
            process_repo(i + 1, slug, owner_repo)
            for i, (slug, owner_repo) in enumerate(candidates)
        ]
    )

    return {
        "repos_searched": total,
        "repos_with_hits": repos_with_hits,
        "issues_found": issues_found,
        "errors": errors,
    }


# ---------------------------------------------------------------------------


def bulk_search() -> None:
    """CLI entry point for bulk issue detection."""
    parser = argparse.ArgumentParser(
        description="Bulk search for trusted-publishing tracking issues"
    )
    parser.add_argument(
        "--target",
        default="./data",
        help="Path to data directory (default: ./data)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of repos to search (default: all)",
    )
    parser.add_argument(
        "--verdict",
        choices=["notp", "unk", "tp"],
        default=None,
        help="Only search repos with this verdict (default: all)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Skip repos already in pending (default: true)",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Re-search repos already in pending",
    )
    args = parser.parse_args()

    stats = asyncio.run(
        _run_bulk_search(
            Path(args.target),
            limit=args.limit,
            verdict_filter=args.verdict,
            resume=args.resume,
        )
    )

    print("\n=== Bulk search complete ===")
    print(f"  Repos searched:  {stats['repos_searched']}")
    print(f"  Repos with hits: {stats['repos_with_hits']}")
    print(f"  Issues found:    {stats['issues_found']}")
    print(f"  Errors:          {stats['errors']}\n")
    print("Pending issues are in data/tracker/pending/ — use the tracker app to triage.")

    sys.exit(0 if stats["errors"] == 0 else 1)