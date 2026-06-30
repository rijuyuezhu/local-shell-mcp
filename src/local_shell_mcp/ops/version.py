"""Version-reporting operation helpers."""

from ..schemas.result_models.version import VersionInfoOutput
from ..version import version_info


def version_info_execute() -> VersionInfoOutput:
    """Return typed runtime and package version metadata."""
    return VersionInfoOutput(**version_info())
