from pathlib import Path

import polars as pl

from .defaults import resolve_report, resolve_results


def _build_verdicts(target: Path, results_meta: dict) -> pl.DataFrame:
    """Read classification dirs and produce a name→verdict mapping."""
    rows = []
    for verdict in ("tp", "notp", "unk"):
        key = f"{verdict}_dir"
        d = target / results_meta[key]
        if not d.exists():
            continue
        for link in d.iterdir():
            if link.is_symlink():
                rows.append({"name": link.name, "verdict": verdict})

    return pl.DataFrame(rows, schema={"name": pl.Utf8, "verdict": pl.Utf8})


_KEEP_COLS = [
    "rank",
    "name",
    "version",
    "summary",
    "uploaded_via",
    "upload_time",
    "filename",
    "recent_7d_downloads",
    "github_url",
]


def generate_report(
    name: str | None = None,
    target: Path | str = "./data",
) -> Path:
    """
    Join repo_urls.parquet with classification verdicts and write a TSV report.
    """
    target = Path(target)
    report_meta = resolve_report(name)
    results_meta = resolve_results(name)

    source = target / report_meta["source"]
    if not source.exists():
        raise FileNotFoundError(
            f"Source parquet not found at {source} — run tp-repo-urls first"
        )

    df = pl.read_parquet(source).select(
        [c for c in _KEEP_COLS if c in pl.read_parquet_schema(source)]
    )

    verdicts = _build_verdicts(target, results_meta)
    result = df.join(verdicts, on="name", how="left")

    out_path = target / report_meta["output"]
    result.sort("rank").write_csv(out_path, separator="\t")

    counts = result.group_by("verdict").len().sort("verdict")
    for row in counts.iter_rows(named=True):
        print(f"  {row['verdict'] or 'unclassified'}: {row['len']}")

    print(f"\nReport written to {out_path} ({result.height} rows)")

    mini_path = out_path.with_stem(out_path.stem + "_mini")
    result.select("rank", "name", "verdict").sort("rank").write_csv(
        mini_path, separator="\t"
    )
    print(f"Mini report written to {mini_path}")

    return out_path
