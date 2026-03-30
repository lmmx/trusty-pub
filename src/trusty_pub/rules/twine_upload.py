"""
Rule: detect `twine upload` invocations in workflow run steps.

Negative (notp):
  - Step or job `env:` contains TWINE_USERNAME or TWINE_PASSWORD
  - The twine upload line itself contains inline credentials:
    `-u`, `-p`, `--username`, `--password`, `__token__`, or `secrets.`

Only uncommented lines are considered — a `#` before `twine upload`
on the same line means it's not a real invocation.

No positive indicator is defined yet — twine-based TP workflows have
not been characterised. Everything else defers.
"""

import re
from pathlib import Path

from trusty_pub.workflow_parser import all_run_commands

_TWINE_UPLOAD_RE = re.compile(r"\btwine\s+upload\b")

_NOTP_ENV_KEYS = {"TWINE_USERNAME", "TWINE_PASSWORD"}

# Patterns on the twine upload line itself that indicate token-based auth
_NOTP_LINE_PATTERNS = [
    re.compile(r"\s-[up]\s"),  # -u or -p with surrounding spaces
    re.compile(r"\s-[up]$"),  # -u or -p at end of line
    re.compile(r"--username\b"),
    re.compile(r"--password\b"),
    re.compile(r"__token__"),
    re.compile(r"secrets\."),
]


def _is_commented(line: str) -> bool:
    """Check if the twine upload on this line is in a bash comment."""
    stripped = line.lstrip()
    return stripped.startswith("#")


def _classify_command(cmd) -> str | None:
    """
    Given a RunCommand containing `twine upload`, return a verdict.

    Checks env blocks and inline credentials on the upload line.
    """
    # Check step-level and job-level env
    if _NOTP_ENV_KEYS & cmd.env.keys():
        return "notp"
    if _NOTP_ENV_KEYS & cmd.job_env.keys():
        return "notp"

    # Collapse backslash-continued lines into logical lines
    collapsed = re.sub(r"\\\s*\n\s*", " ", cmd.command)

    # Check each uncommented logical line that has twine upload
    for line in collapsed.splitlines():
        if not _TWINE_UPLOAD_RE.search(line):
            continue
        if _is_commented(line):
            continue

        for pat in _NOTP_LINE_PATTERNS:
            if pat.search(line):
                return "notp"

    return None


def rule(pkg_name: str, workflow_path: Path) -> str | None:
    """
    Scan all workflow files for `twine upload` invocations.

    Returns notp if any invocation has credential indicators.
    Defers otherwise.
    """
    workflows_dir = workflow_path / ".github" / "workflows"
    commands = all_run_commands(workflows_dir, prefilter="twine upload")

    verdicts: set[str] = set()

    for cmd in commands:
        if not _TWINE_UPLOAD_RE.search(cmd.command):
            continue
        v = _classify_command(cmd)
        if v is not None:
            verdicts.add(v)

    if len(verdicts) == 1:
        return verdicts.pop()

    return None
