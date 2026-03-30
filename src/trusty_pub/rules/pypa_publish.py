"""
Rule: detect `pypa/gh-action-pypi-publish` usage in workflow steps.

Two sub-rules, applied per-invocation:

  Positive (tp):
    The job has `permissions: { id-token: write }`.
    This is mandatory for Trusted Publishing and cannot appear by accident.

  Negative (notp):
    The step's `with:` block sets `user` or `password`.
    This means a token/password is being passed explicitly — not TP.

If both signals appear in different jobs/files → defer (needs manual review).
If neither signal is present → defer.
"""

from pathlib import Path

from trusty_pub.workflow_parser import all_action_invocations

_ACTION_PREFIX = "pypa/gh-action-pypi-publish"

_TOKEN_WITH_KEYS = {"user", "password"}


def _is_pypa_publish(uses: str) -> bool:
    return uses.split("@")[0].strip() == _ACTION_PREFIX


def _is_testpypi(inv) -> bool:
    repo_url = inv.with_.get("repository-url", "")
    return "test.pypi" in repo_url


def _classify_invocation(inv) -> str | None:
    has_id_token = inv.job_permissions.get("id-token") == "write"
    has_token_with = bool(_TOKEN_WITH_KEYS & inv.with_.keys())

    if has_id_token and not has_token_with:
        return "tp"
    if has_token_with and not has_id_token:
        return "notp"

    return None


def rule(pkg_name: str, workflow_path: Path) -> str | None:
    workflows_dir = workflow_path / ".github" / "workflows"
    invocations = all_action_invocations(
        workflows_dir, prefilter="pypa/gh-action-pypi-publish"
    )

    verdicts: set[str] = set()

    for inv in invocations:
        if not _is_pypa_publish(inv.uses):
            continue
        if _is_testpypi(inv):
            continue
        v = _classify_invocation(inv)
        if v is not None:
            verdicts.add(v)

    if len(verdicts) == 1:
        return verdicts.pop()

    return None
