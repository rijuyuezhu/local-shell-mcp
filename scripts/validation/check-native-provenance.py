#!/usr/bin/env python3
"""Verify documented native-artifact inputs and distribution notices."""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROVENANCE = REPO / "docs" / "maintenance" / "native-artifact-provenance.md"
EXPECTED_HASHES = {
    "ui-opentui/package.json": "dac1801bc8f6ae034ba092bb780a173f30cd47f343d626f43bb3895df1920238",
    "ui-opentui/bun.lock": "5412a17ab4bbd8695c361f944bf5286302c8635a548643cf7ad2a4653b0ef8b3",
    "src/local_shell_mcp/ui/contracts.py": "7938a33666c851a66450973dddb6b4d04ef29078bc7e338ddaa310d7392a3f29",
    "scripts/generation/generate-tui-executable-contract.py": "9458dfa30bb24008967e011409f38b54df5b6ca9eed766f62645bc9e8d21fef2",
    "ui-opentui/scripts/executable-contract.ts": "424e7b00f8acfac0e20f7432891b916a67df852ae4b39ec46730728a7fa1e9f0",
    "ui-opentui/scripts/compile-tui.ts": "2a51b3ccc85a5823d3ad28676ebadcce951651c517b9f15c6d77e00778d4abb8",
    "scripts/build-platform-wheel.py": "93968eb5af540f686cb83dc572b8c8445603b0ff0a540dafd676d3c1fa8010a5",
    "scripts/smoke-platform-wheel.py": "8c4b48d29850bfd532636c4afd11d747bd671cee3d696c41f3b4533198a3f653",
    "scripts/tmux-helper.Dockerfile": "b544bc5199834db5d7df4a6471a0237950223f9c4b392e53acb7658d87bac693",
    "scripts/build-tmux-helper.sh": "9147408366451272afe90396e63dd76f1809e641e48fc7861a8a2fd2304d825a",
    "src/local_shell_mcp/helpers/tmux.LICENSE": "c031bd37f464c534277814f6aa38686fa023d094261d57fd2545ad592bb53ccd",
    "src/local_shell_mcp/helpers/opentui.NOTICES": "73d026453521d235c1df46f2dcf90943661258695e8eed87ba2c91e7caa03e61",
    "src/local_shell_mcp/helpers/bun-1.3.14.LICENSE.md": "2c6160ec8fb853f7e8f97d9b249e756c9b0ac44860a68b6bf4f1b0bcbc5c3741",
}


def _sha256(path: Path) -> str:
    # Git may check text files out as CRLF on Windows. Hash the canonical UTF-8
    # text with universal-newline normalization so one locked source has the
    # same digest on every supported runner.
    normalized = path.read_text(encoding="utf-8").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def main() -> int:
    provenance = PROVENANCE.read_text(encoding="utf-8")
    failures: list[str] = []
    for relative, expected in EXPECTED_HASHES.items():
        actual = _sha256(REPO / relative)
        if actual != expected:
            failures.append(f"{relative}: expected {expected}, got {actual}")
        if expected not in provenance:
            failures.append(
                f"{relative}: hash is not recorded in provenance docs"
            )

    required_fragments = {
        "scripts/generation/generate-tui-executable-contract.py": "render_contract",
        "ui-opentui/scripts/compile-tui.ts": 'from "./executable-contract"',
        "pyproject.toml": '"src/local_shell_mcp/helpers/opentui.NOTICES"',
        ".github/workflows/release.yml": "BUN-1.3.14-LICENSE.md",
        "scripts/validation/check-release-matrix.py": '"BUN-1.3.14-LICENSE.md"',
        "mkdocs.yml": "maintenance/native-artifact-provenance.md",
        "scripts/tmux-helper.Dockerfile": (
            "ARG TMUX_SHA256="
            "16216bd0877170dfcc64157085ba9013610b12b082548c7c9542cc0103198951"
        ),
    }
    repository_only = {".github/workflows/release.yml", "mkdocs.yml"}
    for relative, fragment in required_fragments.items():
        path = REPO / relative
        if not path.exists() and relative in repository_only:
            continue
        text = path.read_text(encoding="utf-8")
        if fragment not in text:
            failures.append(f"{relative}: missing {fragment!r}")

    if failures:
        print("Native artifact provenance check failed.")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(
        "Native artifact provenance matches locked OpenTUI/tmux inputs, notices, "
        "and release packaging."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
