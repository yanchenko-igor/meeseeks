"""Shell execution tool — run commands in the sandbox."""

from __future__ import annotations

import subprocess

from meeseeks.tools.registry import ToolRegistry


def register_shell_tools(registry: ToolRegistry, timeout: int = 60) -> None:
    registry.add(
        name="run_command",
        description="Execute a shell command. Returns stdout and stderr. Use this for running tests, building, checking outputs, etc.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
            },
            "required": ["command"],
        },
        handler=lambda cwd, command: _run_command(cwd, command, timeout),
    )


def _run_command(cwd: str, command: str, timeout: int) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds"

    output_parts: list[str] = []
    if result.stdout:
        output_parts.append(result.stdout)
    if result.stderr:
        output_parts.append(f"STDERR:\n{result.stderr}")
    if result.returncode != 0:
        output_parts.append(f"EXIT CODE: {result.returncode}")

    if not output_parts:
        return "Command completed successfully (no output)"

    return "\n".join(output_parts)
