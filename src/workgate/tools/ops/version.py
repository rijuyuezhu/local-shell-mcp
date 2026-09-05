"""Version-reporting operation helpers."""

from ...version import version_info
from ..schemas.result_models.version import VersionInfoOutput


def version_info_execute() -> VersionInfoOutput:
    """Return typed runtime and package version metadata."""
    return VersionInfoOutput(**version_info())
