"""File operation tools — read, write, edit."""

from __future__ import annotations

import os
import pathlib

from meeseeks.tools.registry import ToolRegistry


def register_file_tools(registry: ToolRegistry) -> None:
    registry.add(
        name="read_file",
        description="Read the contents of a file. Returns the full content with line numbers. Use offset/limit for large files.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (relative to cwd)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start from (0-indexed, default 0)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to read (default 2000)",
                },
            },
            "required": ["path"],
        },
        handler=_read_file,
    )

    registry.add(
        name="write_file",
        description="Write content to a file. Creates parent directories if needed. Overwrites existing content.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (relative to cwd)",
                },
                "content": {
                    "type": "string",
                    "description": "The full content to write",
                },
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
    )

    registry.add(
        name="edit_file",
        description="Edit an existing file by replacing an exact string match. The old_str must match exactly (including whitespace).",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file (relative to cwd)",
                },
                "old_str": {
                    "type": "string",
                    "description": "The exact string to find and replace",
                },
                "new_str": {
                    "type": "string",
                    "description": "The replacement string",
                },
            },
            "required": ["path", "old_str", "new_str"],
        },
        handler=_edit_file,
    )


def _read_file(cwd: str, path: str, offset: int = 0, limit: int = 2000) -> str:
    full_path = pathlib.Path(cwd) / path
    if not full_path.exists():
        return f"Error: File not found: {path}"
    if not full_path.is_file():
        return f"Error: Not a file: {path}"

    try:
        content = full_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"Error: Cannot read binary file: {path}"

    lines = content.splitlines()
    total = len(lines)
    selected = lines[offset : offset + limit]

    numbered = [f"{i + offset + 1}: {line}" for i, line in enumerate(selected)]
    header = f"{path} ({total} lines"
    if offset > 0 or offset + limit < total:
        header += f", showing {offset + 1}-{min(offset + limit, total)}"
    header += ")"

    return header + "\n" + "\n".join(numbered)


def _write_file(cwd: str, path: str, content: str) -> str:
    full_path = pathlib.Path(cwd) / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")
    return f"Written {len(content)} bytes to {path}"


def _edit_file(cwd: str, path: str, old_str: str, new_str: str) -> str:
    full_path = pathlib.Path(cwd) / path
    if not full_path.exists():
        return f"Error: File not found: {path}"

    content = full_path.read_text(encoding="utf-8")
    count = content.count(old_str)

    if count == 0:
        return f"Error: old_str not found in {path}. Make sure it matches exactly (including whitespace)."
    if count > 1:
        return f"Error: old_str found {count} times in {path}. Provide more context to make it unique."

    new_content = content.replace(old_str, new_str, 1)
    full_path.write_text(new_content, encoding="utf-8")
    return f"Edited {path}: replaced {len(old_str)} chars with {len(new_str)} chars"
