#!/usr/bin/env python3
"""Verify generated-reference widgets resolve to files in a built MkDocs site."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse


class _GeneratedReferenceParser(HTMLParser):
    """Collect generated-reference JSON URLs from one rendered HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        """Record JSON URLs from generated-reference div elements."""
        if tag != "div":
            return
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if "generated-reference" in classes:
            self.urls.append(values.get("data-reference-json") or "")


def generated_reference_targets(
    site_dir: Path,
) -> list[tuple[Path, str, Path]]:
    """Return every reference widget and its resolved local JSON target."""
    site_root = site_dir.resolve()
    targets: list[tuple[Path, str, Path]] = []
    for page in sorted(site_root.rglob("*.html")):
        parser = _GeneratedReferenceParser()
        parser.feed(page.read_text(encoding="utf-8"))
        for raw_url in parser.urls:
            parsed = urlparse(raw_url)
            if parsed.scheme or parsed.netloc or raw_url.startswith("/"):
                raise ValueError(
                    f"{page.relative_to(site_root)} uses a non-local reference URL: "
                    f"{raw_url!r}"
                )
            target = (page.parent / unquote(parsed.path)).resolve()
            if not target.is_relative_to(site_root):
                raise ValueError(
                    f"{page.relative_to(site_root)} reference escapes site root: "
                    f"{raw_url!r}"
                )
            targets.append((page, raw_url, target))
    return targets


def check_generated_reference_assets(site_dir: Path) -> list[str]:
    """Return validation errors for generated-reference widgets in a built site."""
    site_root = site_dir.resolve()
    if not site_root.is_dir():
        return [f"built site directory does not exist: {site_root}"]
    errors: list[str] = []
    try:
        targets = generated_reference_targets(site_root)
    except ValueError as exc:
        return [str(exc)]
    if not targets:
        return ["built site contains no generated-reference widgets"]
    for page, raw_url, target in targets:
        if not raw_url:
            errors.append(
                f"{page.relative_to(site_root)} has an empty data-reference-json"
            )
        elif not target.is_file():
            errors.append(
                f"{page.relative_to(site_root)} -> {raw_url!r} is missing "
                f"({target.relative_to(site_root)})"
            )
        elif target.suffix != ".json":
            errors.append(
                f"{page.relative_to(site_root)} -> {raw_url!r} is not JSON"
            )
    return errors


def main() -> int:
    """Validate a built site and print each resolved generated-reference asset."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    args = parser.parse_args()
    errors = check_generated_reference_assets(args.site_dir)
    if errors:
        print("Generated reference asset check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    site_root = args.site_dir.resolve()
    targets = generated_reference_targets(site_root)
    for page, raw_url, target in targets:
        print(
            f"{page.relative_to(site_root)} -> {raw_url} -> "
            f"{target.relative_to(site_root)}"
        )
    print(f"Generated reference asset check passed for {len(targets)} page(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
