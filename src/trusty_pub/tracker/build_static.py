"""Build static site from tracker dataset."""
from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import polars as pl

_STATIC_SRC = Path(__file__).parent / "static_site"


def build(data: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    # copy all static assets (html, css, js, resources.json)
    for f in _STATIC_SRC.iterdir():
        if f.is_file():
            shutil.copy2(f, out / f.name)

    # load data
    report = pl.read_csv(data / "report_mini.tsv", separator="\t")
    urls = pl.read_parquet(data / "repo_urls.parquet", columns=["name", "github_url"])
    df = report.join(urls, on="name", how="left").sort("rank")

    # read tracked issues
    tracked: dict[str, list] = {}
    repos_dir = data / "tracker" / "repos"
    if repos_dir.exists():
        for d in (d for d in repos_dir.iterdir() if d.is_dir()):
            issues = []
            for f in sorted(d.glob("*.toml")):
                try:
                    rec = tomllib.loads(f.read_text())
                    issues.append([
                        int(f.stem), rec["title"], rec["state"],
                        rec.get("keyword", ""), rec["issue_url"],
                    ])
                except (ValueError, tomllib.TOMLDecodeError, KeyError):
                    continue
            if issues:
                owner, repo = d.name.split("__", 1)
                tracked[f"https://github.com/{owner}/{repo}"] = issues

    # compact JSON: [rank, name, verdict, ?gh_url, ?issues]
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
    print(f"✓ {len(rows)} pkgs, {len(tracked)} tracked → "
          f"{out / 'data.json'} ({len(blob) // 1024}KB)")