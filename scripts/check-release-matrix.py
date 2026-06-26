#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
EXPECTED_BINARY_ARTIFACTS = {
    "linux-x86_64",
    "linux-aarch64",
    "macos-x86_64",
    "macos-aarch64",
    "windows-x86_64",
}
EXPECTED_DOCKER_PLATFORMS = {"linux/amd64", "linux/arm64"}


def _section(text: str, start_pattern: str, end_pattern: str) -> str:
    start = re.search(start_pattern, text, flags=re.MULTILINE)
    if start is None:
        raise SystemExit(f"missing section matching {start_pattern!r}")
    end = re.search(end_pattern, text[start.end() :], flags=re.MULTILINE)
    if end is None:
        return text[start.start() :]
    return text[start.start() : start.end() + end.start()]


def _release_binary_artifacts(text: str) -> set[str]:
    build_binary = _section(
        text,
        r"^  build-binary:\n",
        r"^  [A-Za-z0-9_-]+:\n",
    )
    return set(
        re.findall(
            r"^          - artifact: ([A-Za-z0-9_-]+)$",
            build_binary,
            flags=re.MULTILINE,
        )
    )


def _release_docker_platforms(text: str) -> set[str]:
    docker_job = _section(
        text,
        r"^  publish-docker-platform:\n",
        r"^  [A-Za-z0-9_-]+:\n",
    )
    return set(
        re.findall(
            r"^          - platform: ([A-Za-z0-9_/-]+)$",
            docker_job,
            flags=re.MULTILINE,
        )
    )


def _report_mismatch(kind: str, expected: set[str], actual: set[str]) -> int:
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if not missing and not extra:
        return 0
    print(f"Release {kind} mismatch.")
    print(f"missing: {missing}")
    print(f"extra: {extra}")
    return 1


def main() -> int:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    binary_status = _report_mismatch(
        "binary matrix",
        EXPECTED_BINARY_ARTIFACTS,
        _release_binary_artifacts(text),
    )
    docker_status = _report_mismatch(
        "Docker platform",
        EXPECTED_DOCKER_PLATFORMS,
        _release_docker_platforms(text),
    )
    if binary_status or docker_status:
        return 1
    print(
        "Release workflow covers expected binary artifacts and Docker platforms."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
