#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
DOCKERFILE = REPO / "Dockerfile"
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


def _require_fragments(kind: str, text: str, fragments: tuple[str, ...]) -> int:
    missing = [fragment for fragment in fragments if fragment not in text]
    if not missing:
        return 0
    print(f"Release {kind} is incomplete.")
    for fragment in missing:
        print(f"missing fragment: {fragment}")
    return 1


def main() -> int:
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
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
    opentui_release_status = _require_fragments(
        "OpenTUI sidecar packaging",
        _section(text, r"^  build-binary:\n", r"^  [A-Za-z0-9_-]+:\n"),
        (
            "oven-sh/setup-bun@v2",
            "bun install --frozen-lockfile",
            "bun run build:tui",
            "ui-opentui/dist/local-shell-mcp-tui.exe",
            "ui-opentui/dist/local-shell-mcp-tui",
            "helper_platform: linux/amd64",
            "helper_platform: linux/arm64",
            "helper_tag: linux-x86_64",
            "helper_tag: linux-aarch64",
            "scripts/build-tmux-helper.sh",
            "--add-binary",
            "pyi-archive_viewer",
            "local_shell_mcp/helpers/${{ matrix.helper_tag }}/tmux",
            "TMUX-LICENSE.txt",
        ),
    )
    opentui_docker_status = _require_fragments(
        "OpenTUI Docker packaging",
        dockerfile,
        (
            "FROM oven/bun:1.3.14 AS opentui-build",
            "bun install --frozen-lockfile",
            "bun run build:tui",
            "/usr/local/bin/local-shell-mcp-tui",
        ),
    )
    if (
        binary_status
        or docker_status
        or opentui_release_status
        or opentui_docker_status
    ):
        return 1
    print(
        "Release workflow covers expected binary artifacts, Docker platforms, "
        "OpenTUI sidecars, and bundled Linux tmux helpers."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
