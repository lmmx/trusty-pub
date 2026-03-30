from .no_workflows import rule as no_workflows_rule
from .pypa_publish import rule as pypa_publish_rule
from .twine_upload import rule as twine_upload_rule
from .uv_publish import rule as uv_publish_rule

# Each rule is a callable(pkg_name, workflow_path) -> "tp" | "notp" | None
# workflow_path points to the resolved package dir (through the symlink chain)
# Rules are applied in order; first non-None result wins.
# An empty list means everything stays unknown.

ALL_RULES = [
    no_workflows_rule,
    uv_publish_rule,
    pypa_publish_rule,
    twine_upload_rule,
]
