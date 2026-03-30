from pathlib import Path


def rule(pkg_name: str, workflow_path: Path) -> str | None:
    """No workflows dir at all — cannot be using Trusted Publishing."""
    sentinel = workflow_path / "NO_WORKFLOWS"
    if sentinel.exists():
        return "notp"
    return None