import json
import os
import subprocess
import sys


def test_export_tools_json_writes_wrapped_payload(tmp_path):
    output = tmp_path / "tools.json"
    env = os.environ.copy()
    env.update(
        {
            "LOCAL_SHELL_MCP_AGENT_BRIDGE_ENABLED": "false",
            "LOCAL_SHELL_MCP_REMOTE_ENABLED": "false",
            "PYTHONPATH": "src",
        }
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/export-tools-json.py",
            "--wrapped",
            "--output",
            str(output),
        ],
        check=True,
        cwd=".",
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.stdout == ""
    payload = json.loads(output.read_text())
    assert payload["count"] == len(payload["tools"])
    assert {tool["name"] for tool in payload["tools"]} >= {
        "environment_info",
        "read_file",
        "run_shell_command",
    }
