"""
Rule: detect reusable workflow calls that pass a PyPI token via `secrets:`.

Negative (notp):
  A job uses a reusable workflow (job-level `uses:`) and passes a secret
  whose key or value references a PyPI token pattern.

This catches patterns like:
  jobs:
    publish:
      uses: org/repo/.github/workflows/publish.yml@main
      secrets:
        PYPI_TOKEN: ${{ secrets.PYPI_TOKEN }}
"""

import re
from pathlib import Path

import yaml

from trusty_pub.workflow_parser import workflow_files, _read_text

_TOKEN_PATTERNS = re.compile(
    r"PYPI.*TOKEN|TOKEN.*PYPI|PYPI.*PASSWORD|PYPI.*KEY|PYPI.*SECRET",
    re.IGNORECASE,
)


def rule(pkg_name: str, workflow_path: Path) -> str | None:
    workflows_dir = workflow_path / ".github" / "workflows"

    verdicts: set[str] = set()

    for path in workflow_files(workflows_dir):
        text = _read_text(path)
        if text is None:
            continue
        if "secrets" not in text:
            continue

        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            continue

        if not isinstance(doc, dict):
            continue
        jobs = doc.get("jobs")
        if not isinstance(jobs, dict):
            continue

        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue

            # Reusable workflows have `uses:` at the job level
            uses = job.get("uses")
            if not isinstance(uses, str):
                continue

            secrets = job.get("secrets")
            if not isinstance(secrets, dict):
                continue

            for key, value in secrets.items():
                if _TOKEN_PATTERNS.search(str(key)) or _TOKEN_PATTERNS.search(
                    str(value)
                ):
                    verdicts.add("notp")

    if len(verdicts) == 1:
        return verdicts.pop()

    return None