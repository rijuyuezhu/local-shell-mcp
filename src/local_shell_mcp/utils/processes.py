"""Small cross-platform subprocess launch contracts."""

import os
import subprocess
from typing import Any


def new_process_group_kwargs(
    *,
    windows: bool | None = None,
    windows_creation_flag: int | None = None,
) -> dict[str, Any]:
    """Return asyncio subprocess kwargs for one isolated child process group."""
    use_windows = os.name == "nt" if windows is None else windows
    if not use_windows:
        return {"start_new_session": True}
    creation_flag = (
        int(vars(subprocess)["CREATE_NEW_PROCESS_GROUP"])
        if windows_creation_flag is None
        else windows_creation_flag
    )
    return {"creationflags": creation_flag}
