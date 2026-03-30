"""
Rule: detect `uv publish` invocations in workflow run steps.

Positive (tp):
  - `--trusted-publishing` flag is present

Negative (notp):
  - `--token` flag is present
  - `TOKEN` appears (env var reference like ${{ secrets.PYPI_TOKEN }})
  - `PASS` appears (env var reference like ${{ secrets.PYPI_PASSWORD }})

Neutral (defer → None):
  - `uv publish` with no decisive flags — absence of evidence is not evidence
"""

import re
from pathlib import Path

from trusty_pub.workflow_parser import all_run_commands

# Each line in a `run:` block that contains `uv publish` (not as a substring
# of something else — word boundary on the left, command boundary on the right)
_UV_PUBLISH_RE = re.compile(r"\buv\s+publish\b")

# Positive indicators: this command is explicitly using Trusted Publishing
_TP_INDICATORS = [
    re.compile(r"--trusted-publishing"),
]

# Negative indicators: this command is using a token/password (not TP)
_NOTP_INDICATORS = [
    re.compile(r"--token\b"),
    re.compile(r"TOKEN"),
    re.compile(r"PASS"),
]


def _classify_command(command: str) -> str | None:
    """
    Given the text of a run step containing `uv publish`, return a verdict.

    Returns "tp", "notp", or None (defer).
    """
    # Check each line that actually has `uv publish`
    for line in command.splitlines():
        if not _UV_PUBLISH_RE.search(line):
            continue

        # Positive indicators take priority — explicit opt-in
        for pat in _TP_INDICATORS:
            if pat.search(line):
                return "tp"

        # Negative indicators
        for pat in _NOTP_INDICATORS:
            if pat.search(line):
                return "notp"

    # uv publish is present but no decisive flags — defer
    return None


def rule(pkg_name: str, workflow_path: Path) -> str | None:
    """
    Scan all workflow files for `uv publish` invocations.

    If any invocation is decisively tp or notp, return that.
    If invocations exist but are all ambiguous, defer (None).
    If no `uv publish` found at all, defer (None) — a different rule
    may handle this package.
    """
    workflows_dir = workflow_path / ".github" / "workflows"
    commands = all_run_commands(workflows_dir, prefilter="uv publish")

    verdicts: set[str] = set()

    for cmd in commands:
        if not _UV_PUBLISH_RE.search(cmd.command):
            continue
        v = _classify_command(cmd.command)
        if v is not None:
            verdicts.add(v)

    # If we see both tp and notp in different steps/files, defer —
    # this needs manual review
    if len(verdicts) == 1:
        return verdicts.pop()

    return None
