"""
Rule: detect `hatch publish` invocations in workflow run steps.

Negative (notp):
  - Step or job env contains HATCH_INDEX_USER, HATCH_INDEX_AUTH,
    HATCH_USER, or HATCH_AUTH
  - The hatch publish line contains inline credentials:
    `-u`, `-a`, `__token__`, or `secrets.`

No positive indicator defined yet. Everything else defers.
"""

import re
from pathlib import Path

from trusty_pub.workflow_parser import all_run_commands

_HATCH_PUBLISH_RE = re.compile(r"\bhatch\s+publish\b")

_NOTP_ENV_KEYS = {
    "HATCH_INDEX_USER",
    "HATCH_INDEX_AUTH",
    "HATCH_USER",
    "HATCH_AUTH",
}

_NOTP_LINE_PATTERNS = [
    re.compile(r"\s-u\s"),
    re.compile(r"\s-u$"),
    re.compile(r"\s-a\s"),
    re.compile(r"\s-a$"),
    re.compile(r"__token__"),
    re.compile(r"secrets\."),
]


def _is_commented(line: str) -> bool:
    return line.lstrip().startswith("#")


def _classify_command(cmd) -> str | None:
    if _NOTP_ENV_KEYS & cmd.env.keys():
        return "notp"
    if _NOTP_ENV_KEYS & cmd.job_env.keys():
        return "notp"

    collapsed = re.sub(r"\\\s*\n\s*", " ", cmd.command)

    for line in collapsed.splitlines():
        if not _HATCH_PUBLISH_RE.search(line):
            continue
        if _is_commented(line):
            continue

        for pat in _NOTP_LINE_PATTERNS:
            if pat.search(line):
                return "notp"

    return None


def rule(pkg_name: str, workflow_path: Path) -> str | None:
    workflows_dir = workflow_path / ".github" / "workflows"
    commands = all_run_commands(workflows_dir, prefilter="hatch publish")

    verdicts: set[str] = set()

    for cmd in commands:
        if not _HATCH_PUBLISH_RE.search(cmd.command):
            continue
        v = _classify_command(cmd)
        if v is not None:
            verdicts.add(v)

    if len(verdicts) == 1:
        return verdicts.pop()

    return None