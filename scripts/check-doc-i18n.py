#!/usr/bin/env python3
"""Validate maintained localized MkDocs pages and navigation coverage."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
MKDOCS = REPO / "mkdocs.yml"
DOCS = REPO / "docs"

REQUIRED_ZH_PAGES = (
    "index.zh.md",
    "getting-started/quickstart.zh.md",
    "guides/human-interface.zh.md",
    "guides/remote-workers.zh.md",
    "guides/agent-bridge.zh.md",
    "security.zh.md",
    "troubleshooting.zh.md",
)
PLACEHOLDER_PHRASES = (
    "Runtime defines how the server process runs",
    "Use this page when the selected Runtime or Client path matches the title",
    "Choose the Runtime installation page first",
    "confirms runtime settings and workspace",
    "Prefer small, verifiable steps",
    "## Documentation paths",
    "## Core architecture",
    "## Key safety rule",
    "localized version",
    "Tool names, parameter names",
    "Search workspace files and return ChatGPT connector-compatible results",
    "**Overview.**",
    "**Inputs.**",
    "**Returns.**",
    "Common combinations",
)

MIN_LOCALIZED_CHARACTERS = 150
MIN_CJK_CHARACTERS = 80


class _MkDocsLoader(yaml.SafeLoader):
    """Safe loader that preserves trusted MkDocs Python-name tags as strings."""


def _python_name_tag(
    loader: _MkDocsLoader, suffix: str, node: yaml.Node
) -> str:
    """Return a Python-name tag as inert text without importing or executing it."""
    del loader, node
    return suffix


_MkDocsLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:", _python_name_tag
)


def collect_nav_titles(items: Iterable[object]) -> set[str]:
    """Return every human-facing title from a nested MkDocs nav tree."""
    titles: set[str] = set()
    for item in items:
        if isinstance(item, str):
            titles.add(item)
            continue
        if not isinstance(item, dict):
            continue
        for title, value in item.items():
            titles.add(str(title))
            if isinstance(value, list):
                titles.update(collect_nav_titles(value))
    return titles


def _i18n_languages(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the configured i18n language rows or fail with a useful message."""
    for plugin in config.get("plugins", []):
        if isinstance(plugin, dict) and "i18n" in plugin:
            value = plugin["i18n"]
            if isinstance(value, dict) and isinstance(
                value.get("languages"), list
            ):
                return [
                    row for row in value["languages"] if isinstance(row, dict)
                ]
    raise ValueError("mkdocs.yml does not configure plugins.i18n.languages")


def _english_peer(localized: Path) -> Path:
    """Return the English source path for one suffix-structured localized page."""
    return localized.with_name(localized.name.removesuffix(".zh.md") + ".md")


def _check_localized_page(path: Path) -> list[str]:
    """Return quality errors for one maintained Simplified Chinese page."""
    errors: list[str] = []
    relative = path.relative_to(REPO)
    if not path.is_file():
        return [f"missing maintained page: {relative}"]
    text = path.read_text(encoding="utf-8")
    if len(text.strip()) < MIN_LOCALIZED_CHARACTERS:
        errors.append(f"{relative}: localized page is too short")
    if not text.lstrip().startswith("# "):
        errors.append(f"{relative}: page must begin with an H1 heading")
    cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
    if cjk_count < MIN_CJK_CHARACTERS:
        errors.append(
            f"{relative}: expected at least {MIN_CJK_CHARACTERS} CJK characters, found {cjk_count}"
        )
    for phrase in PLACEHOLDER_PHRASES:
        if phrase in text:
            errors.append(
                f"{relative}: stale placeholder phrase remains: {phrase}"
            )
            break
    peer = _english_peer(path)
    if not peer.is_file():
        errors.append(
            f"{relative}: missing English source page {peer.relative_to(REPO)}"
        )
    elif text.strip() == peer.read_text(encoding="utf-8").strip():
        errors.append(
            f"{relative}: localized page is identical to English source"
        )
    return errors


def main() -> int:
    """Validate language configuration, nav translations, and maintained pages."""
    config = yaml.load(MKDOCS.read_text(encoding="utf-8"), Loader=_MkDocsLoader)
    if not isinstance(config, dict):
        print("Documentation i18n check failed: mkdocs.yml must be a mapping")
        return 1
    nav_titles = collect_nav_titles(config.get("nav", []))
    errors: list[str] = []
    languages = _i18n_languages(config)
    locales = {str(row.get("locale")) for row in languages}
    if locales != {"en", "zh"}:
        errors.append(
            "mkdocs.yml must build exactly the maintained locales en and zh; "
            f"found {sorted(locales)}"
        )

    for language in languages:
        locale = str(language.get("locale"))
        if locale == "en":
            if language.get("default") is not True:
                errors.append("en must remain the default documentation locale")
            continue
        translations = language.get("nav_translations", {})
        if not isinstance(translations, dict):
            errors.append(f"{locale}: nav_translations must be a mapping")
            continue
        missing = sorted(nav_titles - set(map(str, translations)))
        extra = sorted(set(map(str, translations)) - nav_titles)
        if missing:
            errors.append(
                f"{locale}: missing nav translations: {', '.join(missing)}"
            )
        if extra:
            errors.append(
                f"{locale}: stale nav translations: {', '.join(extra)}"
            )

    for relative in REQUIRED_ZH_PAGES:
        errors.extend(_check_localized_page(DOCS / relative))

    localized_pages = {
        path.relative_to(DOCS).as_posix() for path in DOCS.rglob("*.zh.md")
    }
    unexpected = sorted(localized_pages - set(REQUIRED_ZH_PAGES))
    if unexpected:
        errors.append(
            "untracked maintained zh pages must be added to REQUIRED_ZH_PAGES: "
            + ", ".join(unexpected)
        )

    if errors:
        print("Documentation i18n check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "Documentation i18n check passed: complete zh navigation and "
        f"{len(REQUIRED_ZH_PAGES)} maintained localized pages."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
