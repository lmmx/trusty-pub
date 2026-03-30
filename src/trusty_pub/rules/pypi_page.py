"""
Rule: check the PyPI project page for Trusted Publishing status.

Fetches https://pypi.org/project/{name}/ and looks for the per-file
indicator string:

  "Uploaded using Trusted Publishing? Yes" → tp
  "Uploaded using Trusted Publishing? No"  → notp

If both appear (mixed releases), tp takes priority — the package
has TP configured even if older releases predate it.

This rule is a last resort and makes HTTP requests. It should be
placed last in ALL_RULES.
"""

import asyncio
import time
from pathlib import Path

import httpx
from tqdm import tqdm

# Module-level cache: populated once per classify run, shared across calls
_cache: dict[str, str | None] = {}
_cache_populated = False

_TP_YES = "Uploaded using Trusted Publishing? Yes"
_TP_NO = "Uploaded using Trusted Publishing? No"

_HEADERS = {
    "User-Agent": "trusty-pub/0.1.0 (https://github.com/lmmx/trusty-pub; louismmx@gmail.com)"
}


async def _fetch_all(names: list[str], concurrency: int = 5) -> dict[str, str | None]:
    """Fetch PyPI pages for all names and return verdicts."""
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, str | None] = {}
    pbar = tqdm(total=len(names), desc="Checking PyPI pages", unit="pkg")

    async def _fetch_one(client: httpx.AsyncClient, name: str) -> None:
        async with sem:
            try:
                r = await client.get(
                    f"https://pypi.org/project/{name}/",
                    follow_redirects=True,
                )
                if r.status_code != 200:
                    results[name] = None
                else:
                    text = r.text
                    has_yes = _TP_YES in text
                    has_no = _TP_NO in text

                    if has_yes:
                        results[name] = "tp"
                    elif has_no:
                        results[name] = "notp"
                    else:
                        results[name] = None
            except Exception:
                results[name] = None
            finally:
                pbar.update(1)
                await asyncio.sleep(0.2)

    async with httpx.AsyncClient(headers=_HEADERS, timeout=30) as client:
        tasks = [_fetch_one(client, n) for n in names]
        await asyncio.gather(*tasks)

    pbar.close()
    return results


def _ensure_cache(workflow_path: Path) -> None:
    """No-op — cache is populated externally by prime_cache."""
    pass


def prime_cache(names: list[str]) -> None:
    """
    Fetch all PyPI pages upfront. Call this once before the classify loop
    so we batch the HTTP requests instead of doing them one at a time.
    """
    global _cache, _cache_populated
    if _cache_populated:
        return
    _cache = asyncio.run(_fetch_all(names))
    _cache_populated = True


def reset_cache() -> None:
    """Reset cache between runs (e.g. in tests)."""
    global _cache, _cache_populated
    _cache = {}
    _cache_populated = False


def rule(pkg_name: str, workflow_path: Path) -> str | None:
    return _cache.get(pkg_name)