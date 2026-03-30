# src/trusty_pub/classify.py
from pathlib import Path

from .defaults import resolve_results
from .rules import ALL_RULES

_REL_PACKAGES = Path("../../workflows/packages")


# ---------------------------------------------------------------------------
# State: read / write symlinks in the three classification dirs
# ---------------------------------------------------------------------------

def _read_dir(directory: Path) -> set[str]:
    """Return package names present as symlinks in a classification dir."""
    if not directory.exists():
        return set()
    return {p.name for p in directory.iterdir() if p.is_symlink()}


def _add(name: str, directory: Path) -> None:
    """Create a symlink directory/name → ../../workflows/packages/name."""
    link = directory / name
    if not link.is_symlink():
        link.symlink_to(_REL_PACKAGES / name)


def _remove(name: str, directory: Path) -> None:
    """Remove a symlink from a classification dir if it exists."""
    link = directory / name
    if link.is_symlink():
        link.unlink()


# ---------------------------------------------------------------------------
# Invariant: a package must never appear in more than one dir
# ---------------------------------------------------------------------------

def _check_invariant(tp: set[str], notp: set[str], unk: set[str]) -> None:
    pairs = [("tp", "notp", tp & notp), ("tp", "unk", tp & unk), ("notp", "unk", notp & unk)]
    violations = [(a, b, overlap) for a, b, overlap in pairs if overlap]
    if violations:
        lines = [
            f"  {a} ∩ {b}: {sorted(overlap)[:10]}"
            for a, b, overlap in violations
        ]
        total = sum(len(o) for _, _, o in violations)
        raise RuntimeError(
            f"{total} package(s) in multiple classification dirs:\n"
            + "\n".join(lines)
        )


# ---------------------------------------------------------------------------
# Phase 1: seed — ensure every package appears in exactly one dir
# ---------------------------------------------------------------------------

def _seed(
    all_packages: set[str],
    tp: set[str],
    notp: set[str],
    unk: set[str],
    unk_dir: Path,
) -> set[str]:
    """
    Any package not yet in tp/notp/unk gets added to unk.

    Returns the updated unk set.
    """
    missing = all_packages - tp - notp - unk
    for pkg in sorted(missing):
        _add(pkg, unk_dir)
    return unk | missing


# ---------------------------------------------------------------------------
# Phase 2: evaluate — run rules against unk, produce verdicts
# ---------------------------------------------------------------------------

def _evaluate(
    unk: set[str],
    packages_dir: Path,
) -> tuple[set[str], set[str], set[str]]:
    """
    Run every rule against every unknown package.

    Returns (promote_tp, promote_notp, still_unk) — three disjoint sets.
    """
    promote_tp: set[str] = set()
    promote_notp: set[str] = set()

    for pkg in sorted(unk):
        resolved = (packages_dir / pkg).resolve()

        verdict = None
        for rule in ALL_RULES:
            verdict = rule(pkg, resolved)
            if verdict is not None:
                break

        if verdict == "tp":
            promote_tp.add(pkg)
        elif verdict == "notp":
            promote_notp.add(pkg)

    still_unk = unk - promote_tp - promote_notp
    return promote_tp, promote_notp, still_unk


# ---------------------------------------------------------------------------
# Phase 3: commit — move symlinks from unk into tp/notp
# ---------------------------------------------------------------------------

def _commit(
    promote_tp: set[str],
    promote_notp: set[str],
    tp_dir: Path,
    notp_dir: Path,
    unk_dir: Path,
) -> None:
    """Move promoted packages out of unk and into their target dirs."""
    for pkg in sorted(promote_tp):
        _remove(pkg, unk_dir)
        _add(pkg, tp_dir)

    for pkg in sorted(promote_notp):
        _remove(pkg, unk_dir)
        _add(pkg, notp_dir)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def classify(
    name: str | None = None,
    target: Path | str = "./data",
) -> Path:
    """
    Classify packages into tp / notp / unk based on workflow analysis.

    Phase 1 (seed):     new packages → unk
    Phase 2 (evaluate): run rules against all unk
    Phase 3 (commit):   move decided packages from unk → tp or notp
    """
    target = Path(target)
    meta = resolve_results(name)

    packages_dir = target / meta["packages_dir"]
    tp_dir = target / meta["tp_dir"]
    notp_dir = target / meta["notp_dir"]
    unk_dir = target / meta["unk_dir"]

    for d in (tp_dir, notp_dir, unk_dir):
        d.mkdir(parents=True, exist_ok=True)

    all_packages = {p.name for p in packages_dir.iterdir() if p.is_symlink()}
    if not all_packages:
        raise FileNotFoundError(
            f"No packages found in {packages_dir} — run tp-fetch-workflows first"
        )

    # Load existing state and verify consistency
    tp = _read_dir(tp_dir)
    notp = _read_dir(notp_dir)
    unk = _read_dir(unk_dir)
    _check_invariant(tp, notp, unk)

    # Phase 1: seed new packages into unk
    unk = _seed(all_packages, tp, notp, unk, unk_dir)

    # Phase 2: evaluate all unknowns
    promote_tp, promote_notp, still_unk = _evaluate(unk, packages_dir)

    # Phase 3: commit promotions
    _commit(promote_tp, promote_notp, tp_dir, notp_dir, unk_dir)

    # Final state
    final_tp = tp | promote_tp
    final_notp = notp | promote_notp
    _check_invariant(final_tp, final_notp, still_unk)

    print(
        f"tp: {len(final_tp)}, notp: {len(final_notp)}, unk: {len(still_unk)}\n"
        f"  promoted: {len(promote_tp)} → tp, {len(promote_notp)} → notp\n"
        f"  remaining unknown: {len(still_unk)}"
    )

    return tp_dir.parent