import json
import shutil
import subprocess
from pathlib import Path

import pytest

RENDERER = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "workgate"
    / "ui"
    / "static"
    / "terminal_renderer.js"
)


def _parse_ansi(value: str) -> list[dict]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for browser renderer tests")
    script = """
const fs = require("fs");
const renderer = require(process.argv[1]);
const value = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(renderer.parseAnsi(value)));
"""
    completed = subprocess.run(
        [node, "-e", script, str(RENDERER)],
        input=json.dumps(value),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_terminal_renderer_preserves_sgr_and_resets():
    runs = _parse_ansi("plain \x1b[1;31mred\x1b[22;39m normal")

    assert runs == [
        {
            "text": "plain ",
            "bold": False,
            "dim": False,
            "italic": False,
            "underline": False,
            "inverse": False,
            "hidden": False,
            "strike": False,
            "fg": None,
            "bg": None,
        },
        {
            "text": "red",
            "bold": True,
            "dim": False,
            "italic": False,
            "underline": False,
            "inverse": False,
            "hidden": False,
            "strike": False,
            "fg": "rgb(255, 123, 139)",
            "bg": None,
        },
        {
            "text": " normal",
            "bold": False,
            "dim": False,
            "italic": False,
            "underline": False,
            "inverse": False,
            "hidden": False,
            "strike": False,
            "fg": None,
            "bg": None,
        },
    ]


def test_terminal_renderer_preserves_zero_extended_colors():
    runs = _parse_ansi("\x1b[38;2;0;0;0mtrue-black\x1b[48;5;0m indexed-black")

    assert runs[0]["fg"] == "rgb(0, 0, 0)"
    assert runs[0]["bg"] is None
    assert runs[1]["fg"] == "rgb(0, 0, 0)"
    assert runs[1]["bg"] == "rgb(7, 17, 31)"


def test_terminal_renderer_strips_active_and_non_sgr_controls():
    value = (
        "before"
        "\x1b]8;;javascript:alert(1)\x07linked\x1b]8;;\x07"
        "\x1bPprivate payload\x1b\\"
        "\x1b[2J"
        "\u009d8;;javascript:alert(2)\x07c1-link\u009d8;;\x07"
        "\u0090c1-private\u009c"
        "after"
    )

    runs = _parse_ansi(value)

    serialized = json.dumps(runs)
    assert "".join(run["text"] for run in runs) == "beforelinkedc1-linkafter"
    assert "javascript" not in serialized
    assert "private payload" not in serialized
    assert "c1-private" not in serialized


def test_terminal_renderer_bounds_run_count_without_losing_visible_text():
    value = "".join(f"\x1b[{30 + index % 8}mX" for index in range(10_100))

    runs = _parse_ansi(value)

    assert len(runs) <= 10_000
    assert "".join(run["text"] for run in runs) == "X" * 10_100


def test_terminal_renderer_uses_inert_dom_primitives_only():
    source = RENDERER.read_text(encoding="utf-8")

    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "createTextNode" in source
    assert "span.textContent = run.text" in source
    assert "replaceChildren" in source
