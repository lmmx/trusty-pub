"""Dependency-graph analysis of Trusted Publishing coverage."""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
from packaging.requirements import InvalidRequirement, Requirement

from .defaults import resolve_analysis


def _norm(name: str) -> str:
    """PEP 503 name normalisation."""
    return re.sub(r"[-_.]+", "-", name).lower()


_NORM = pl.col("name").str.to_lowercase().str.replace_all(r"[-_.]+", "-")


def _parse_runtime_dep_names(specs: list[str] | None) -> list[str]:
    """Extract normalised package names from a requires_dist list.

    Skips deps gated behind an ``extra`` marker (optional dependency groups)
    but keeps environment markers like ``python_version``.
    """
    if specs is None:
        return []
    names: list[str] = []
    for spec in specs:
        try:
            req = Requirement(spec)
        except InvalidRequirement:
            continue
        if req.marker and "extra" in str(req.marker):
            continue
        names.append(_norm(req.name))
    return names


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_and_merge(target: Path, meta: dict) -> pl.DataFrame:
    """Join report verdicts, requires_dist from parquet, and hugo vk downloads."""
    report = pl.read_csv(target / meta["report_mini"], separator="\t").with_columns(
        _NORM.alias("norm_name")
    )

    deps = pl.read_parquet(
        target / meta["parquet"], columns=["name", "requires_dist"]
    ).with_columns(_NORM.alias("norm_name"))

    downloads = (
        pl.read_csv(target / meta["downloads"])
        .rename({"project": "name"})
        .with_columns(_NORM.alias("norm_name"))
    )

    return report.join(
        deps.select("norm_name", "requires_dist"), on="norm_name", how="left"
    ).join(downloads.select("norm_name", "download_count"), on="norm_name", how="left")


# ---------------------------------------------------------------------------
# Edge list
# ---------------------------------------------------------------------------


def _build_edges(merged: pl.DataFrame) -> pl.DataFrame:
    """Build a (package → dep) edge list with looked-up dep verdicts."""
    verdict_lookup: dict[str, str] = dict(
        zip(merged["norm_name"].to_list(), merged["verdict"].to_list())
    )

    rows: list[dict] = []
    for rec in merged.iter_rows(named=True):
        for dep in _parse_runtime_dep_names(rec["requires_dist"]):
            dep_verdict = verdict_lookup.get(dep)
            rows.append(
                {
                    "norm_name": rec["norm_name"],
                    "verdict": rec["verdict"],
                    "dep_norm_name": dep,
                    "dep_in_dataset": dep_verdict is not None,
                    "dep_verdict": dep_verdict,
                }
            )

    if not rows:
        return pl.DataFrame(
            schema={
                "norm_name": pl.Utf8,
                "verdict": pl.Utf8,
                "dep_norm_name": pl.Utf8,
                "dep_in_dataset": pl.Boolean,
                "dep_verdict": pl.Utf8,
            }
        )

    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# Per-package coverage
# ---------------------------------------------------------------------------


def _per_package_coverage(merged: pl.DataFrame, edges: pl.DataFrame) -> pl.DataFrame:
    """Per-package stats: how many direct deps are TP / non-TP."""
    total_deps = edges.group_by("norm_name").agg(pl.len().alias("n_direct_deps"))

    in_dataset = edges.filter(pl.col("dep_in_dataset"))
    dep_stats = (
        in_dataset.group_by("norm_name")
        .agg(
            pl.len().alias("n_in_dataset"),
            (pl.col("dep_verdict") == "tp").sum().alias("n_tp"),
            (pl.col("dep_verdict") == "notp").sum().alias("n_notp"),
            (pl.col("dep_verdict") == "unk").sum().alias("n_unk"),
        )
        .with_columns(
            (pl.col("n_tp") / pl.col("n_in_dataset")).alias("dep_tp_ratio"),
        )
    )

    return (
        merged.select("rank", "name", "norm_name", "verdict", "download_count")
        .join(total_deps, on="norm_name", how="left")
        .join(dep_stats, on="norm_name", how="left")
        .sort("rank")
    )


# ---------------------------------------------------------------------------
# Weakest links
# ---------------------------------------------------------------------------


def _weakest_links(edges: pl.DataFrame, merged: pl.DataFrame) -> pl.DataFrame:
    """Rank non-TP packages by how many TP packages directly depend on them."""
    notp_deps = edges.filter(
        pl.col("dep_in_dataset") & (pl.col("dep_verdict") == "notp")
    )

    dl_lookup = merged.select(
        pl.col("norm_name").alias("dep_norm_name"),
        pl.col("download_count").alias("own_download_count"),
    )

    return (
        notp_deps.group_by("dep_norm_name")
        .agg(
            pl.len().alias("n_dependents"),
            (pl.col("verdict") == "tp").sum().alias("n_tp_dependents"),
        )
        .join(dl_lookup, on="dep_norm_name", how="left")
        .rename({"dep_norm_name": "name"})
        .sort("n_tp_dependents", descending=True)
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_TIERS = [100, 360, 1000, 5000, 15000]


def _print_stats(
    merged: pl.DataFrame, coverage: pl.DataFrame, weakest: pl.DataFrame
) -> None:
    print("\n=== TP adoption by tier ===\n")

    for tier in _TIERS:
        t = merged.filter(pl.col("rank") <= tier)
        total = t.height
        tp_n = t.filter(pl.col("verdict") == "tp").height
        tp_pct = tp_n / total * 100 if total else 0

        total_dl = t["download_count"].sum() or 0
        tp_dl = t.filter(pl.col("verdict") == "tp")["download_count"].sum() or 0
        dl_pct = tp_dl / total_dl * 100 if total_dl else 0

        print(
            f"  Top {tier:>5}:  {tp_pct:5.1f}% by count ({tp_n}/{total}),"
            f"  {dl_pct:5.1f}% by downloads"
        )

    print("\n=== Dependency TP coverage ===\n")

    tp_with_deps = coverage.filter(
        (pl.col("verdict") == "tp") & pl.col("n_in_dataset").is_not_null()
    )
    if tp_with_deps.height > 0:
        exposed = tp_with_deps.filter(pl.col("n_notp") > 0).height
        pct = exposed / tp_with_deps.height * 100
        print(
            f"  TP packages with >=1 non-TP direct dep:"
            f"  {exposed}/{tp_with_deps.height} ({pct:.1f}%)"
        )

    all_with_deps = coverage.filter(pl.col("n_in_dataset").is_not_null())
    if all_with_deps.height > 0:
        median = all_with_deps["dep_tp_ratio"].median()
        mean = all_with_deps["dep_tp_ratio"].mean()
        print(f"  Median dep TP ratio (packages with resolvable deps):  {median:.2f}")
        print(f"  Mean dep TP ratio:  {mean:.2f}")

    print(
        "\n=== Top 20 weakest links"
        " (non-TP packages most depended on by TP packages) ===\n"
    )
    for row in weakest.head(20).iter_rows(named=True):
        print(
            f"  {row['name']:35s}"
            f"  {row['n_tp_dependents']:>4} TP dependents"
            f"  {row['n_dependents']:>4} total"
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def run_analysis(
    name: str | None = None,
    target: Path | str = "./data",
) -> Path:
    """
    Cross-reference TP verdicts with dependency metadata to produce
    per-package TP coverage stats and a weakest-links ranking.
    """
    target = Path(target)
    meta = resolve_analysis(name)

    output_dir = target / meta["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading and joining sources...")
    merged = _load_and_merge(target, meta)

    print(f"Building dependency edges for {merged.height} packages...")
    edges = _build_edges(merged)
    print(
        f"  {edges.height} edges, {edges.filter(pl.col('dep_in_dataset')).height} resolvable within dataset"
    )

    coverage = _per_package_coverage(merged, edges)
    weakest = _weakest_links(edges, merged)

    _print_stats(merged, coverage, weakest)

    # Write outputs
    cov_path = output_dir / "dep_coverage.tsv"
    coverage.drop("norm_name").write_csv(cov_path, separator="\t")
    print(f"\nDep coverage written to {cov_path} ({coverage.height} rows)")

    wl_path = output_dir / "weakest_links.tsv"
    weakest.write_csv(wl_path, separator="\t")
    print(f"Weakest links written to {wl_path} ({weakest.height} rows)")

    return output_dir
