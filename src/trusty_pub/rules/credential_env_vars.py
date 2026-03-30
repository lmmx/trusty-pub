"""
Rule: detect PyPI credential env vars set on any step or job.

Negative (notp):
  Known credential env vars are present in a step or job env block.
  These only exist to authenticate via tokens — not Trusted Publishing.

This catches cases where the actual upload command is wrapped behind
tox, make, nox, a shell script, etc.
"""

from pathlib import Path

from trusty_pub.workflow_parser import all_run_commands

_NOTP_ENV_KEYS = {
    # twine
    "TWINE_USERNAME",
    "TWINE_PASSWORD",
    # hatch
    "HATCH_INDEX_USER",
    "HATCH_INDEX_AUTH",
    # poetry
    "POETRY_PYPI_TOKEN_PYPI",
    "POETRY_HTTP_BASIC_PYPI_PASSWORD",
    "POETRY_HTTP_BASIC_PYPI_USERNAME",
    # flit
    "FLIT_USERNAME",
    "FLIT_PASSWORD",
}


def rule(pkg_name: str, workflow_path: Path) -> str | None:
    workflows_dir = workflow_path / ".github" / "workflows"
    # No prefilter — we're matching on env keys, not run text
    commands = all_run_commands(workflows_dir)

    for cmd in commands:
        if _NOTP_ENV_KEYS & cmd.env.keys():
            return "notp"
        if _NOTP_ENV_KEYS & cmd.job_env.keys():
            return "notp"

    return None