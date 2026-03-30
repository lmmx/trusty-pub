import asyncio
import os
import shutil
from pathlib import Path

import polars as pl
from grepow.core import RepoFiles, clone_sparse
from tqdm import tqdm

from .defaults import resolve_workflows


def _build_mappings(
    target: Path, source_file: str
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """
    Load repo_urls.parquet, derive slug column, return unique repos and
    package-to-slug mapping.
    """
    df = (
        pl.scan_parquet(target / source_file)
        .select("name", "github_url", "rank")
        .filter(pl.col("github_url").is_not_null())
        .with_columns(
            pl.col("github_url")
            .str.replace("https://github.com/", "")
            .str.replace("/", "__")
            .alias("slug"),
        )
        .collect()
    )

    unique_repos = df.select("slug", "github_url").unique(subset="slug")
    package_to_slug = df.select("name", "slug")

    return unique_repos, package_to_slug


async def _clone_repos(
    unique_repos: pl.DataFrame,
    repos_dir: Path,
    concurrency: int = 10,
    max_retries: int = 3,
    base_backoff: float = 30.0,
) -> list[dict]:
    """Clone .github/workflows for each unique repo. Returns list of failures."""
    repos_dir.mkdir(parents=True, exist_ok=True)

    to_clone = []
    skipped = 0
    for row in unique_repos.iter_rows(named=True):
        slug_dir = repos_dir / row["slug"]
        workflows_dir = slug_dir / ".github" / "workflows"
        sentinel = slug_dir / "NO_WORKFLOWS"
        if workflows_dir.exists() or sentinel.exists():
            skipped += 1
        else:
            to_clone.append(row)

    print(f"{len(to_clone)} repos to clone, {skipped} already cached")

    if not to_clone:
        return []

    sem = asyncio.Semaphore(concurrency)
    failures = []
    pbar = tqdm(total=len(to_clone), desc="Cloning", unit="repo")

    async def _clone_one(row: dict, attempt: int = 1) -> None:
        slug = row["slug"]
        owner_repo = row["github_url"].removeprefix("https://github.com/")
        slug_dir = repos_dir / slug

        async with sem:
            try:
                try:
                    repo = RepoFiles(owner_repo=owner_repo, paths=[".github/workflows"])
                    await asyncio.wait_for(
                        clone_sparse(repo, repos_dir),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError(f"clone timed out for {owner_repo}")

                cloned_dir = repos_dir / owner_repo.replace("/", "__")
                if cloned_dir != slug_dir and cloned_dir.exists():
                    if slug_dir.exists():
                        shutil.rmtree(slug_dir)
                    cloned_dir.rename(slug_dir)

                git_dir = slug_dir / ".git"
                if git_dir.exists():
                    shutil.rmtree(git_dir)

                workflows_dir = slug_dir / ".github" / "workflows"
                if not workflows_dir.exists() or not any(workflows_dir.iterdir()):
                    github_dir = slug_dir / ".github"
                    if github_dir.exists():
                        shutil.rmtree(github_dir)
                    slug_dir.mkdir(parents=True, exist_ok=True)
                    (slug_dir / "NO_WORKFLOWS").touch()

            except Exception as exc:
                error_msg = str(exc).lower()
                is_rate_limit = (
                    "authentication" in error_msg
                    or "terminal prompts disabled" in error_msg
                    or "could not read" in error_msg
                    or "128" in error_msg
                )

                if is_rate_limit and attempt < max_retries:
                    delay = base_backoff * (2 ** (attempt - 1))
                    pbar.set_postfix_str(f"rate limited, waiting {delay:.0f}s")
                    await asyncio.sleep(delay)
                    await _clone_one(row, attempt + 1)
                    return
                else:
                    # Clean up partial clone
                    if slug_dir.exists():
                        shutil.rmtree(slug_dir)
                    failures.append(
                        {
                            "slug": slug,
                            "github_url": row["github_url"],
                            "error": str(exc),
                        }
                    )
            finally:
                pbar.update(1)

    tasks = [_clone_one(row) for row in to_clone]
    await asyncio.gather(*tasks)
    pbar.close()

    return failures


def _create_symlinks(
    package_to_slug: pl.DataFrame,
    repos_dir: Path,
    packages_dir: Path,
) -> tuple[int, int]:
    """Create package name → repo slug symlinks. Returns (created, skipped)."""
    packages_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0

    for row in package_to_slug.iter_rows(named=True):
        name = row["name"]
        slug = row["slug"]
        link = packages_dir / name
        target = Path("../repos") / slug

        if not (repos_dir / slug).exists():
            skipped += 1
            continue

        if link.is_symlink() or link.exists():
            link.unlink()

        link.symlink_to(target)
        created += 1

    return created, skipped


def fetch_workflows(
    name: str | None = None,
    target: Path | str = "./data",
) -> Path:
    """
    Clone .github/workflows for all packages with a GitHub URL.
    Creates repo dirs and package-name symlinks.
    """
    target = Path(target)
    meta = resolve_workflows(name)

    repos_dir = target / meta["repos_dir"]
    packages_dir = target / meta["packages_dir"]

    unique_repos, package_to_slug = _build_mappings(target, meta["source"])

    print(
        f"{unique_repos.height} unique repos, "
        f"{package_to_slug.height} package→repo mappings"
    )

    # Clone
    failures = asyncio.run(_clone_repos(unique_repos, repos_dir))

    # Write failures
    if failures:
        failures_path = target / "workflows" / "failures.csv"
        pl.DataFrame(failures).write_csv(failures_path)
        print(f"{len(failures)} failures written to {failures_path}")

    # Symlinks
    created, skipped = _create_symlinks(package_to_slug, repos_dir, packages_dir)

    print(
        f"Done: {unique_repos.height - len(failures)} repos cloned, "
        f"{len(failures)} failed, "
        f"{created} symlinks created, "
        f"{skipped} skipped (missing repo)"
    )

    return repos_dir
