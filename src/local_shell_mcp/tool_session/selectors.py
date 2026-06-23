"""Parse oh-my-pi inspired path selectors for agent read tools."""

import re
from dataclasses import dataclass

_LINE_SELECTOR_RE = re.compile(
    r"^(?P<start>\d+)(?:(?P<mode>[-+])(?P<end>\d*)?)?$"
)


@dataclass(frozen=True)
class ReadTarget:
    """A path plus optional display selectors parsed from one read target."""

    path: str
    """Workspace path with recognized selector suffixes removed."""

    start_line: int | None
    """Optional 1-based first line selected by the target."""

    end_line: int | None
    """Optional 1-based final line selected by the target."""

    raw: bool
    """Whether model-facing output should omit added line-number prefixes."""


def _parse_line_selector(selector: str) -> tuple[int, int | None] | None:
    """Return a 1-based line range for a supported line selector."""
    match = _LINE_SELECTOR_RE.match(selector)
    if match is None:
        return None
    start = int(match.group("start"))
    mode = match.group("mode")
    end_text = match.group("end")
    if start < 1:
        return None
    if mode is None or mode == "-" and not end_text:
        return start, None
    if mode == "-":
        end = int(end_text)
        if end < start:
            return None
        return start, end
    if mode == "+":
        count = int(end_text)
        if count < 1:
            return None
        return start, start + count - 1
    return None


def parse_read_target(target: str) -> ReadTarget:
    """Parse a read target with optional ':raw' and line-range suffixes.

    Supported suffixes intentionally mirror the most useful oh-my-pi forms:
    ':50' and ':50-' read from line 50 through the end, ':50-80' reads an
    inclusive range, ':50+20' reads 20 lines starting at line 50, and ':raw'
    keeps the model-facing output unnumbered.  Suffixes may be combined as
    ':50-80:raw' or ':raw:50-80'.
    """
    if not target:
        raise ValueError("read target path must not be empty")

    parts = target.split(":")
    raw = False
    line_range: tuple[int, int | None] | None = None
    while len(parts) > 1:
        suffix = parts[-1]
        if suffix == "raw":
            raw = True
            parts.pop()
            continue
        parsed_range = _parse_line_selector(suffix)
        if parsed_range is not None and line_range is None:
            line_range = parsed_range
            parts.pop()
            continue
        break

    path = ":".join(parts)
    if not path:
        raise ValueError("read target path must not be empty")
    start_line, end_line = line_range or (None, None)
    return ReadTarget(
        path=path,
        start_line=start_line,
        end_line=end_line,
        raw=raw,
    )
