"""Search tools — glob, grep, list_dir."""

from __future__ import annotations

import fnmatch
import os
import pathlib
import re

from meeseeks.tools.registry import ToolRegistry


def register_search_tools(registry: ToolRegistry) -> None:
    registry.add(
        name="list_dir",
        description="List files and directories at a path. Shows directory structure.",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path (relative to cwd, default '.')",
                },
            },
        },
        handler=_list_dir,
    )

    registry.add(
        name="glob",
        description="Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match files against",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (relative to cwd, default '.')",
                },
            },
            "required": ["pattern"],
        },
        handler=_glob,
    )

    registry.add(
        name="grep",
        description="Search file contents using regex. Returns matching lines with file paths and line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (relative to cwd, default '.')",
                },
                "include": {
                    "type": "string",
                    "description": "File pattern to include (e.g. '*.py', '*.ts')",
                },
            },
            "required": ["pattern"],
        },
        handler=_grep,
    )


def _list_dir(cwd: str, path: str = ".") -> str:
    full_path = pathlib.Path(cwd) / path
    if not full_path.exists():
        return f"Error: Directory not found: {path}"
    if not full_path.is_dir():
        return f"Error: Not a directory: {path}"

    entries: list[str] = []
    try:
        for entry in sorted(full_path.iterdir()):
            prefix = "  " if entry.is_file() else "d "
            entries.append(f"{prefix}{entry.name}")
    except PermissionError:
        return f"Error: Permission denied: {path}"

    if not entries:
        return f"{path}/ (empty)"

    return f"{path}/ ({len(entries)} entries)\n" + "\n".join(entries)


def _glob(cwd: str, pattern: str, path: str = ".") -> str:
    full_path = pathlib.Path(cwd) / path
    if not full_path.exists():
        return f"Error: Path not found: {path}"

    matches = sorted(full_path.glob(pattern))
    if not matches:
        return f"No files matched pattern: {pattern}"

    # Make paths relative to cwd
    results = []
    for m in matches[:200]:  # cap at 200 results
        try:
            rel = m.relative_to(cwd)
        except ValueError:
            rel = m
        results.append(str(rel))

    header = f"Found {len(results)} files"
    if len(matches) > 200:
        header += f" (showing first 200 of {len(matches)})"
    return header + "\n" + "\n".join(results)


def _grep(cwd: str, pattern: str, path: str = ".", include: str | None = None) -> str:
    full_path = pathlib.Path(cwd) / path
    if not full_path.exists():
        return f"Error: Path not found: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex: {e}"

    matches: list[str] = []
    files_searched = 0

    for root, dirs, files in os.walk(full_path):
        # Skip hidden dirs and common noise
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d not in ("node_modules", "__pycache__", "venv", ".git")
        ]

        for fname in files:
            if include and not fnmatch.fnmatch(fname, include):
                continue

            fpath = pathlib.Path(root) / fname
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue

            files_searched += 1
            for i, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    try:
                        rel = fpath.relative_to(cwd)
                    except ValueError:
                        rel = fpath
                    matches.append(f"{rel}:{i}: {line.strip()}")

                    if len(matches) >= 200:
                        return (
                            f"Found {len(matches)}+ matches (searched {files_searched} files)\n"
                            + "\n".join(matches)
                            + "\n... (truncated)"
                        )

    if not matches:
        return f"No matches found for '{pattern}' (searched {files_searched} files)"

    return f"Found {len(matches)} matches (searched {files_searched} files)\n" + "\n".join(matches)
