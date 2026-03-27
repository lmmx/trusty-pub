import asyncio
import shutil
import json
from pathlib import Path

import polars as pl
from grepow.core import RepoFiles, clone_sparse

from .defaults import resolve_package_listing


def fetch_package_listing(
    name: str | None = None, target: Path | str = "./data"
) -> Path:
    """
    Fetch a package listing from GitHub via grepow, convert rows to CSV, remove git metadata.

    `name` is resolved by the resolver; if None, the resolver picks the canonical TOML entry.
    Returns the CSV path.
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)

    meta = resolve_package_listing(name)
    repo = RepoFiles(owner_repo=meta["repo"], paths=[meta["path"]])

    async def _run():
        await clone_sparse(repo, target)

    asyncio.run(_run())

    repo_dir = target / meta["repo"].replace("/", "__")
    json_path = repo_dir / meta["path"]

    # Remove git metadata
    git_dir = repo_dir / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)

    # Read JSON and convert rows to CSV
    csv_path = target / meta.get("csv", json_path.with_suffix(".csv").name)
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    rows = data["rows"]

    df = pl.DataFrame(rows)
    df.write_csv(csv_path)

    # Optionally delete JSON if you want to discard it
    json_path.unlink()

    return csv_path