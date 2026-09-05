"""Input annotations for native image viewing."""

from typing import Annotated

from pydantic import Field

ImagePathArg = Annotated[
    str,
    Field(
        description=(
            "PNG, JPEG, GIF, or WebP path relative to the explicit session "
            "workdir. Use view_image instead of read for visual inspection."
        )
    ),
]
