import asyncio
import shutil
from pathlib import Path

from grepow.core import RepoFiles, clone_sparse

from .defaults import resolve_package_listing


def fetch_package_listing(
    name: str | None = None, target: Path | str = "./data"
) -> Path:
    """
    Fetch a package listing from GitHub via grepow and remove git metadata.

    `name` is resolved by the resolver; if None, the resolver picks the canonical TOML entry.
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)

    meta = resolve_package_listing(name)
    repo = RepoFiles(owner_repo=meta["repo"], paths=[meta["path"]])

    async def _run():
        await clone_sparse(repo, target)

    asyncio.run(_run())

    repo_dir = target / meta["repo"].replace("/", "__")
    file_path = repo_dir / meta["path"]

    git_dir = repo_dir / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)

    return file_path
