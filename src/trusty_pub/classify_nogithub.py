"""
Classify packages that have no GitHub URL by scraping their PyPI page.

Uses touched empty files (not symlinks) as markers, since there are no
repo dirs to link to.
"""

from pathlib import Path

import polars as pl

from .defaults import resolve_pypi_metadata, resolve_results, resolve_results_nogithub
from .rules.pypi_page import prime_cache, reset_cache


# ---------------------------------------------------------------------------
# State: read / write empty marker files
# ---------------------------------------------------------------------------


def _read_dir(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    return {p.name for p in directory.iterdir() if p.is_file()}


def _add(name: str, directory: Path) -> None:
    marker = directory / name
    if not marker.exists():
        marker.touch()


def _remove(name: str, directory: Path) -> None:
    marker = directory / name
    if marker.exists():
        marker.unlink()


# ---------------------------------------------------------------------------
# Invariant: no package in more than one dir across BOTH result sets
# ---------------------------------------------------------------------------


def _check_cross_invariant(
    target: Path,
    results_meta: dict,
    ng_tp: set[str],
    ng_notp: set[str],
    ng_unk: set[str],
) -> None:
    """Ensure no package appears in both the github-based and nogithub results."""
    gh_all = set()
    for key in ("tp_dir", "notp_dir", "unk_dir"):
        d = target / results_meta[key]
        if d.exists():
            gh_all |= {p.name for p in d.iterdir() if p.is_symlink()}

    ng_all = ng_tp | ng_notp | ng_unk
    overlap = gh_all & ng_all
    if overlap:
        raise RuntimeError(
            f"{len(overlap)} package(s) in both github and nogithub results: "
            f"{sorted(overlap)[:10]}"
        )


def _check_invariant(tp: set[str], notp: set[str], unk: set[str]) -> None:
    pairs = [
        ("tp", "notp", tp & notp),
        ("tp", "unk", tp & unk),
        ("notp", "unk", notp & unk),
    ]
    violations = [(a, b, overlap) for a, b, overlap in pairs if overlap]
    if violations:
        lines = [f"  {a} ∩ {b}: {sorted(overlap)[:10]}" for a, b, overlap in violations]
        total = sum(len(o) for _, _, o in violations)
        raise RuntimeError(
            f"{total} package(s) in multiple classification dirs:\n"
            + "\n".join(lines)
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def classify_nogithub(
    name: str | None = None,
    target: Path | str = "./data",
) -> Path:
    """
    Classify packages with no GitHub URL by scraping their PyPI page.
    """
    target = Path(target)
    meta = resolve_results_nogithub(name)
    metadata_meta = resolve_pypi_metadata(name)
    results_meta = resolve_results(name)

    tp_dir = target / meta["tp_dir"]
    notp_dir = target / meta["notp_dir"]
    unk_dir = target / meta["unk_dir"]

    for d in (tp_dir, notp_dir, unk_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Find packages with no github url
    source = target / metadata_meta["output"]
    if not source.exists():
        raise FileNotFoundError(
            f"Source parquet not found at {source} — run tp-repo-urls first"
        )

    df = pl.read_parquet(source, columns=["name", "github_url"])
    no_github = set(
        df.filter(pl.col("github_url").is_null())
        .get_column("name")
        .to_list()
    )

    if not no_github:
        print("All packages have GitHub URLs — nothing to do")
        return tp_dir.parent

    # Load existing state
    tp = _read_dir(tp_dir)
    notp = _read_dir(notp_dir)
    unk = _read_dir(unk_dir)
    _check_invariant(tp, notp, unk)
    _check_cross_invariant(target, results_meta, tp, notp, unk)

    # Seed: new packages → unk
    missing = no_github - tp - notp - unk
    for pkg in sorted(missing):
        _add(pkg, unk_dir)
    unk = unk | missing

    # Evaluate: scrape PyPI pages for all unknowns
    prime_cache(sorted(unk))

    promote_tp: set[str] = set()
    promote_notp: set[str] = set()

    for pkg in sorted(unk):
        from .rules.pypi_page import rule as pypi_rule

        verdict = pypi_rule(pkg, Path())  # workflow_path unused by this rule
        if verdict == "tp":
            promote_tp.add(pkg)
        elif verdict == "notp":
            promote_notp.add(pkg)

    still_unk = unk - promote_tp - promote_notp

    reset_cache()

    # Commit
    for pkg in sorted(promote_tp):
        _remove(pkg, unk_dir)
        _add(pkg, tp_dir)

    for pkg in sorted(promote_notp):
        _remove(pkg, unk_dir)
        _add(pkg, notp_dir)

    # Final checks
    final_tp = tp | promote_tp
    final_notp = notp | promote_notp
    _check_invariant(final_tp, final_notp, still_unk)
    _check_cross_invariant(target, results_meta, final_tp, final_notp, still_unk)

    print(
        f"tp: {len(final_tp)}, notp: {len(final_notp)}, unk: {len(still_unk)}\n"
        f"  promoted: {len(promote_tp)} → tp, {len(promote_notp)} → notp\n"
        f"  remaining unknown: {len(still_unk)}"
    )

    return tp_dir.parent