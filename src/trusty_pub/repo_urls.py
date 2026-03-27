from pathlib import Path

import polars as pl

from .defaults import resolve_package_listing, resolve_pypi_metadata

# _GITHUB_RE = r"(https?://github\.com/[^\s,]+)"
# Do not take the entire URL, only up to the GitHub repo name part of the URL
_GITHUB_RE = r"(https?://github\.com/[^/\s,#]+/[^/\s,#]+)"


def _extract_github_url(df: pl.DataFrame) -> pl.DataFrame:
    """Add a `github_url` column by coalescing project_urls and home_page."""
    from_project_urls = (
        pl.col("project_urls")
        .list.eval(pl.element().filter(pl.element().str.contains("github.com")).first())
        .list.first()
        .str.extract(_GITHUB_RE)
        .str.replace(r"\.git$|/$", "")
    )

    from_home_page = (
        pl.col("home_page").str.extract(_GITHUB_RE).str.replace(r"\.git$|/$", "")
    )

    return df.with_columns(
        pl.coalesce(from_project_urls, from_home_page).alias("github_url"),
    )


def _normalise_name(col: str = "name") -> pl.Expr:
    return pl.col(col).str.to_lowercase().str.replace_all(r"[-_.]+", "-").alias(col)


def _latest_per_package(metadata: pl.DataFrame) -> pl.DataFrame:
    """Deduplicate to one row per package, keeping the most recent release."""
    return metadata.sort("upload_time", descending=True).group_by("name").first()


def fetch_repo_urls(
    listing_name: str | None = None,
    metadata_name: str | None = None,
    target: Path | str = "./data",
) -> Path:
    """
    Download PyPI metadata from HF, join against the top packages listing,
    extract GitHub repo URLs, and write the result as CSV.

    Returns the output CSV path.
    """
    target = Path(target)
    listing_meta = resolve_package_listing(listing_name)
    metadata_meta = resolve_pypi_metadata(metadata_name)

    listing_csv = target / listing_meta["csv"]
    if not listing_csv.exists():
        msg = f"Package listing not found at {listing_csv} — run tp-refresh-pkgs first"
        raise FileNotFoundError(msg)

    packages = (
        pl.read_csv(listing_csv)
        .with_row_index("rank", offset=1)
        .select(
            "rank",
            pl.col("project").alias("name"),
        )
        .with_columns(_normalise_name())
    )

    hf_metadata = pl.read_parquet(metadata_meta["hf_path"]).with_columns(
        _normalise_name()
    )

    latest = _latest_per_package(hf_metadata)

    # packages needs to be eager for the join, but hf_metadata stays lazy until .collect()
    matched = packages.join(latest, on="name", how="left")
    result = _extract_github_url(matched)

    out_path = target / metadata_meta["output"]
    result.write_parquet(out_path)

    found = result.filter(pl.col("github_url").is_not_null()).height
    print(f"{found}/{result.height} packages resolved to a GitHub repo")

    return out_path
