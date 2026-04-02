"""Build static site data from tracker dataset."""
import json, sys, tomllib
from pathlib import Path
import polars as pl


def build(data: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)

    report = pl.read_csv(data / "report_mini.tsv", separator="\t")
    urls = pl.read_parquet(data / "repo_urls.parquet", columns=["name", "github_url"])
    df = report.join(urls, on="name", how="left").sort("rank")

    # tracked issues keyed by github_url
    tracked: dict[str, list] = {}
    repos_dir = data / "tracker" / "repos"
    if repos_dir.exists():
        for d in (d for d in repos_dir.iterdir() if d.is_dir()):
            issues = []
            for f in sorted(d.glob("*.toml")):
                try:
                    rec = tomllib.loads(f.read_text())
                    issues.append([int(f.stem), rec["title"], rec["state"],
                                   rec.get("keyword", ""), rec["issue_url"]])
                except (ValueError, tomllib.TOMLDecodeError, KeyError):
                    continue
            if issues:
                owner, repo = d.name.split("__", 1)
                tracked[f"https://github.com/{owner}/{repo}"] = issues

    # compact: [rank, name, verdict] | + [gh_url] | + [issues]
    rows = []
    for r in df.to_dicts():
        entry = [r["rank"], r["name"], r["verdict"]]
        gh = r.get("github_url")
        if gh:
            entry.append(gh)
            if gh in tracked:
                entry.append(tracked[gh])
        rows.append(entry)

    blob = json.dumps(rows, separators=(",", ":"))
    (out / "data.json").write_text(blob)
    print(f"✓ {len(rows)} pkgs, {len(tracked)} tracked repos → "
          f"{out / 'data.json'} ({len(blob) // 1024}KB)")


if __name__ == "__main__":
    build(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data"),
        Path(sys.argv[2]) if len(sys.argv) > 2 else Path("site"),
    )