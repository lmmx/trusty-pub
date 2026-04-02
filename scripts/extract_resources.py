"""Extract URLs from tracked issue comments via gh CLI."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

URL_RE = re.compile(r"https?://[^\s)\]>\"',]+")
REPOS_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/tracker/repos")


def fetch_comments(issue_url: str) -> list[dict]:
    """Fetch issue body + comments via gh."""
    result = subprocess.run(
        ["gh", "issue", "view", issue_url, "-c",
         "--json", "body,comments,title,url"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ⚠ gh failed for {issue_url}", file=sys.stderr)
        return []
    return json.loads(result.stdout)


def extract_urls_with_context(text: str, n_chars: int = 120) -> list[dict]:
    """Extract URLs with surrounding context from text."""
    if not text:
        return []
    hits = []
    for m in URL_RE.finditer(text):
        url = m.group().rstrip(".,;:!?)")
        start = max(0, m.start() - n_chars)
        end = min(len(text), m.end() + n_chars)
        context = text[start:end].strip()
        # clean up markdown noise but keep readable
        context = re.sub(r"\n+", " ", context)
        hits.append({"url": url, "context": context})
    return hits


def main():
    all_resources = []

    for toml_path in sorted(REPOS_DIR.rglob("*.toml")):
        rec = tomllib.loads(toml_path.read_text())
        issue_url = rec["issue_url"]
        slug = toml_path.parent.name
        owner, repo = slug.split("__", 1)
        print(f"→ {owner}/{repo} #{toml_path.stem}")

        data = fetch_comments(issue_url)
        if not data:
            continue

        # issue body
        body_urls = extract_urls_with_context(data.get("body", ""))
        for u in body_urls:
            all_resources.append({
                "source_issue": issue_url,
                "source_repo": f"{owner}/{repo}",
                "author": "issue_body",
                **u,
            })

        # comments
        for comment in data.get("comments", []):
            comment_urls = extract_urls_with_context(comment.get("body", ""))
            author = comment.get("author", {}).get("login", "unknown")
            for u in comment_urls:
                all_resources.append({
                    "source_issue": issue_url,
                    "source_repo": f"{owner}/{repo}",
                    "author": author,
                    **u,
                })

    # dedupe by URL, keep first occurrence
    seen = set()
    deduped = []
    for r in all_resources:
        if r["url"] not in seen:
            seen.add(r["url"])
            deduped.append(r)

    out = Path("extracted_resources.json")
    out.write_text(json.dumps(deduped, indent=2))
    print(f"\n✓ {len(deduped)} unique URLs from {len(all_resources)} total → {out}")


if __name__ == "__main__":
    main()