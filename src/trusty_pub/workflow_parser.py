"""
Structured parser for GitHub Actions workflow files.

Extracts run commands from the canonical location:
  jobs.<job_id>.steps[*].run

Only reads .yml/.yaml files. Skips files that fail to parse.
Supports a fast text pre-filter to avoid parsing files that
can't possibly match.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RunCommand:
    """A single shell command from a workflow step."""

    file: Path
    job_id: str
    step_index: int
    step_name: str | None
    command: str
    env: dict[str, str]
    job_env: dict[str, str]


def workflow_files(directory: Path) -> list[Path]:
    """Return all .yml and .yaml files in a directory (non-recursive)."""
    if not directory.exists():
        return []
    return sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix in (".yml", ".yaml")
    )


def _read_text(path: Path) -> str | None:
    """Read file contents, returning None on failure."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_run_commands(path: Path, *, prefilter: str | None = None) -> list[RunCommand]:
    """
    Parse a single workflow file and extract all run commands from job steps.

    If `prefilter` is given, the raw file text is checked for the substring
    before any YAML parsing. Returns [] immediately if absent.
    """
    text = _read_text(path)
    if text is None:
        return []

    if prefilter is not None and prefilter not in text:
        return []

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return []

    if not isinstance(doc, dict):
        return []

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return []

    commands: list[RunCommand] = []

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue

        raw_job_env = job.get("env")
        if isinstance(raw_job_env, dict):
            job_env = {str(k): str(v) for k, v in raw_job_env.items()}
        else:
            job_env = {}

        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            run = step.get("run")
            if not isinstance(run, str):
                continue

            raw_env = step.get("env")
            if isinstance(raw_env, dict):
                step_env = {str(k): str(v) for k, v in raw_env.items()}
            else:
                step_env = {}

            commands.append(
                RunCommand(
                    file=path,
                    job_id=job_id,
                    step_index=i,
                    step_name=step.get("name"),
                    command=run,
                    env=step_env,
                    job_env=job_env,
                )
            )

    return commands


def all_run_commands(
    directory: Path, *, prefilter: str | None = None
) -> list[RunCommand]:
    """Extract all run commands from all workflow files in a directory."""
    commands: list[RunCommand] = []
    for path in workflow_files(directory):
        commands.extend(parse_run_commands(path, prefilter=prefilter))
    return commands


@dataclass(frozen=True)
class ActionInvocation:
    """A step that uses a GitHub Action."""

    file: Path
    job_id: str
    step_index: int
    step_name: str | None
    uses: str
    with_: dict[str, str]
    job_permissions: dict[str, str]


def parse_action_invocations(
    path: Path, *, prefilter: str | None = None
) -> list[ActionInvocation]:
    """
    Parse a workflow file and extract all `uses:` steps, along with
    their `with:` block and the parent job's `permissions:`.
    """
    text = _read_text(path)
    if text is None:
        return []

    if prefilter is not None and prefilter not in text:
        return []

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return []

    if not isinstance(doc, dict):
        return []

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return []

    # Top-level permissions (inherited by jobs that don't override)
    top_permissions = doc.get("permissions")
    if not isinstance(top_permissions, dict):
        top_permissions = {}

    invocations: list[ActionInvocation] = []

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue

        job_perms = job.get("permissions")
        if isinstance(job_perms, dict):
            effective_permissions = {str(k): str(v) for k, v in job_perms.items()}
        else:
            effective_permissions = {str(k): str(v) for k, v in top_permissions.items()}

        steps = job.get("steps")
        if not isinstance(steps, list):
            continue

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str):
                continue

            raw_with = step.get("with")
            if isinstance(raw_with, dict):
                with_block = {str(k): str(v) for k, v in raw_with.items()}
            else:
                with_block = {}

            invocations.append(
                ActionInvocation(
                    file=path,
                    job_id=job_id,
                    step_index=i,
                    step_name=step.get("name"),
                    uses=uses,
                    with_=with_block,
                    job_permissions=effective_permissions,
                )
            )

    return invocations


def all_action_invocations(
    directory: Path, *, prefilter: str | None = None
) -> list[ActionInvocation]:
    """Extract all action invocations from all workflow files in a directory."""
    invocations: list[ActionInvocation] = []
    for path in workflow_files(directory):
        invocations.extend(parse_action_invocations(path, prefilter=prefilter))
    return invocations
