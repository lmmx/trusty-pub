# src/trusty_pub/bulk_search.py

"""
Bulk search for trusted-publishing tracking issues across untracked repos.

Iterates through repos that don't yet have tracked issues, searches their
GitHub issues via ``gh`` CLI (authenticated), and stores matches in a
``pending/`` holding area for manual triage rather than auto-tracking them.

Maintains a searched ledger (searched.tsv) so repos that were searched
successfully but had no results are not re-searched on subsequent runs.

Detects GitHub API rate limits and stops gracefully, allowing --resume
to pick up where it left off.

Usage::

    tp-bulk-search              # search all untracked repos
    tp-bulk-search --limit 50   # cap at 50 repos per run
    tp-bulk-search --verdict notp  # only search repos with notp verdict
    tp-bulk-search --resume     # skip repos already in pending/searched/tracked
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
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
# Rate limit handling
# ---------------------------------------------------------------------------


class RateLimitHit(Exception):
    """Raised when a gh CLI call fails due to GitHub API rate limiting."""

    pass


# ---------------------------------------------------------------------------
# gh helpers (async / concurrent)
# ---------------------------------------------------------------------------


async def _gh_search_one(owner_repo: str, kw: str, max_issues: int) -> list[dict]:
    """Search a single keyword in a repo using the gh CLI.

    Raises RateLimitHit if stderr indicates rate limiting.
    Returns [] only for genuinely empty results or non-rate-limit errors
    (e.g. archived/private repo).
    """
    proc = await asyncio.create_subprocess_exec(
        "gh",
        "issue",
        "list",
        "-R",
        owner_repo,
        "--search",
        f"repo:{owner_repo} " + kw,
        "--json",
        "number,title,url,state,createdAt",
        "--limit",
        str(max_issues),
        "--state",
        "all",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").lower()
        # gh CLI surfaces rate limits via several patterns
        if any(
            phrase in err_text
            for phrase in (
                "rate limit",
                "api rate",
                "secondary rate",
                "abuse detection",
                "retry-after",
                "403",
                "exceeded a secondary",
            )
        ):
            raise RateLimitHit(err_text.strip())
        # Non-rate-limit failure (private, archived, not found, etc.)
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
    """Single parenthesized OR query, properly scoped to the repo.

    Raises RateLimitHit if the GitHub CLI indicates rate limiting.
    """
    if not _valid_owner_repo(owner_repo):
        return []

    if not keywords:
        return []

    # Parenthesize so gh's implicit repo: qualifier scopes all branches
    or_query = "(" + " OR ".join(keywords) + ")"
    issues = await _gh_search_one(owner_repo, or_query, max_issues)

    seen: dict[int, dict] = {}
    for issue in issues:
        issue_number = issue["number"]
        if issue_number in seen:
            continue

        # Best-effort keyword attribution from title
        matched_kw = keywords[0]
        title_lower = issue.get("title", "").lower()
        for kw in keywords:
            if kw.lower() in title_lower:
                matched_kw = kw
                break

        issue["keyword"] = matched_kw
        seen[issue_number] = issue

    return sorted(seen.values(), key=lambda x: x["number"], reverse=True)


# ---------------------------------------------------------------------------
# Searched ledger — the key new piece
# ---------------------------------------------------------------------------

_LEDGER_FILENAME = "searched.tsv"


def _read_searched_ledger(ledger_path: Path) -> set[str]:
    """Read the set of slugs already successfully searched."""
    if not ledger_path.exists():
        return set()
    slugs = set()
    with ledger_path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            slugs.add(row["slug"])
    return slugs


def _append_to_ledger(
    ledger_path: Path,
    slug: str,
    issue_count: int,
) -> None:
    """Append a single entry to the searched ledger."""
    write_header = not ledger_path.exists() or ledger_path.stat().st_size == 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with ledger_path.open("a", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        if write_header:
            writer.writerow(["slug", "searched_at", "issue_count"])
        writer.writerow([slug, now, issue_count])


# ---------------------------------------------------------------------------
# Pending writer (unchanged logic)
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


# ---------------------------------------------------------------------------
# Candidate selection (now respects searched ledger)
# ---------------------------------------------------------------------------


def _get_untracked_slugs(
    target: Path,
    tracker_meta: dict,
    verdict_filter: str | None = None,
) -> list[tuple[str, str]]:
    """Return (slug, owner/repo) pairs for repos not yet tracked, pending, or searched."""
    parquet_path = target / tracker_meta["source"]
    report_path = target / tracker_meta["report"]
    repos_dir = target / tracker_meta["repos_dir"]
    pending_dir = target / tracker_meta["pending_dir"]
    ledger_path = pending_dir.parent / _LEDGER_FILENAME  # tracker/searched.tsv

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

    slugs = df.select("slug").unique().to_series().to_list()

    # Exclude already-tracked repos
    tracked = set()
    if repos_dir.exists():
        tracked = {
            d.name for d in repos_dir.iterdir() if d.is_dir() and any(d.glob("*.toml"))
        }

    # Exclude already-pending repos
    pending = set()
    if pending_dir.exists():
        pending = {
            d.name
            for d in pending_dir.iterdir()
            if d.is_dir() and any(d.glob("*.toml"))
        }

    # Exclude already-searched repos (the new bit)
    searched = _read_searched_ledger(ledger_path)

    result = []
    for slug in sorted(slugs):
        if slug in tracked or slug in pending or slug in searched:
            continue
        if not _SLUG_RE.match(slug):
            continue
        owner_repo = _slug_to_owner_repo(slug)
        if owner_repo:
            result.append((slug, owner_repo))

    return result


# ---------------------------------------------------------------------------
# Main search loop with circuit breaker
# ---------------------------------------------------------------------------


async def _run_bulk_search(
    target: Path,
    limit: int | None = None,
    verdict_filter: str | None = None,
    resume: bool = True,
    max_consecutive_errors: int = 3,
) -> dict:
    """Run the bulk search and return summary stats.

    Stops early if max_consecutive_errors rate-limit errors occur in a row.
    """
    tracker_meta = resolve_tracker()
    bulk_meta = resolve_bulk_search()

    pending_dir = target / tracker_meta["pending_dir"]
    ledger_path = (
        target / tracker_meta["repos_dir"].rsplit("/", 1)[0] / _LEDGER_FILENAME
    )
    # More robust: put ledger at tracker/ level
    ledger_path = target / Path(tracker_meta["repos_dir"]).parent / _LEDGER_FILENAME

    max_issues: int = bulk_meta["max_issues_per_repo"]
    concurrency: int = bulk_meta.get("concurrency", 15)
    sem = asyncio.Semaphore(concurrency)

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
    repos_searched_ok = 0
    rate_limited = False

    # Circuit breaker state
    consecutive_errors = 0
    stop_event = asyncio.Event()

    async def process_repo(idx: int, slug: str, owner_repo: str):
        nonlocal repos_with_hits, issues_found, errors, repos_searched_ok
        nonlocal consecutive_errors, rate_limited

        if stop_event.is_set():
            return

        prefix = f"[{idx}/{total}]"

        # Skip if already pending (for resume mode)
        if resume and (pending_dir / slug).exists():
            print(f"{prefix} {owner_repo} — already pending, skipping")
            return

        async with sem:
            if stop_event.is_set():
                return

            try:
                issues = await _gh_search_issues(owner_repo, all_keywords, max_issues)
            except RateLimitHit as exc:
                consecutive_errors += 1
                errors += 1
                print(
                    f"{prefix} {owner_repo} — RATE LIMITED ({consecutive_errors}/{max_consecutive_errors})"
                )
                if consecutive_errors >= max_consecutive_errors:
                    print(
                        f"\n⚠️  Hit {max_consecutive_errors} consecutive rate-limit errors. "
                        f"Stopping. Re-run with --resume after the rate limit resets.\n"
                    )
                    rate_limited = True
                    stop_event.set()
                return
            except Exception:
                errors += 1
                consecutive_errors += 1
                print(f"{prefix} {owner_repo} — error")
                if consecutive_errors >= max_consecutive_errors:
                    print(
                        f"\n⚠️  {max_consecutive_errors} consecutive errors. Stopping.\n"
                    )
                    stop_event.set()
                return

            # Successful search — reset the consecutive error counter
            consecutive_errors = 0
            repos_searched_ok += 1

            if issues:
                repos_with_hits += 1
                for issue in issues:
                    _write_pending(pending_dir, slug, issue)
                    issues_found += 1
                print(f"{prefix} {owner_repo} — {len(issues)} issue(s)")
            else:
                print(f"{prefix} {owner_repo} — no issues")

            # Record in the ledger regardless of whether issues were found
            _append_to_ledger(ledger_path, slug, len(issues))

    # Process sequentially within concurrency limit to preserve ordering
    # for the circuit breaker. Use gather but with semaphore controlling pace.
    await asyncio.gather(
        *[
            process_repo(i + 1, slug, owner_repo)
            for i, (slug, owner_repo) in enumerate(candidates)
        ]
    )

    return {
        "repos_searched": repos_searched_ok,
        "repos_skipped": total - repos_searched_ok,
        "repos_with_hits": repos_with_hits,
        "issues_found": issues_found,
        "errors": errors,
        "rate_limited": rate_limited,
    }


# ---------------------------------------------------------------------------
# CLI
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
        help="Skip repos already in pending/searched (default: true)",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Re-search repos already in pending",
    )
    parser.add_argument(
        "--reset-ledger",
        action="store_true",
        default=False,
        help="Clear the searched ledger before starting (re-search everything)",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=3,
        help="Consecutive rate-limit errors before stopping (default: 3)",
    )
    args = parser.parse_args()

    target = Path(args.target)

    if args.reset_ledger:
        tracker_meta = resolve_tracker()
        ledger = target / Path(tracker_meta["repos_dir"]).parent / _LEDGER_FILENAME
        if ledger.exists():
            ledger.unlink()
            print(f"Cleared searched ledger: {ledger}")

    stats = asyncio.run(
        _run_bulk_search(
            target,
            limit=args.limit,
            verdict_filter=args.verdict,
            resume=args.resume,
            max_consecutive_errors=args.max_errors,
        )
    )

    print("\n=== Bulk search complete ===")
    print(f"  Repos searched OK: {stats['repos_searched']}")
    print(f"  Repos skipped:     {stats['repos_skipped']}")
    print(f"  Repos with hits:   {stats['repos_with_hits']}")
    print(f"  Issues found:      {stats['issues_found']}")
    print(f"  Errors:            {stats['errors']}")

    if stats["rate_limited"]:
        print(f"\n  ⚠️  Stopped due to rate limiting.")
        print(f"  Run again with --resume after the rate limit resets (~1 hour).")
        print(f"  Already-searched repos are recorded in tracker/searched.tsv\n")

    print(
        "Pending issues are in data/tracker/pending/ — use the tracker app to triage."
    )

    # Exit 2 for rate limit (distinct from 1 for other errors)
    if stats["rate_limited"]:
        sys.exit(2)
    sys.exit(0 if stats["errors"] == 0 else 1)
