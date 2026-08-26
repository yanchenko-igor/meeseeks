"""Tool registry — maps tool names to callables, generates OpenAI schemas."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[..., str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> Callable[..., str]:
        """Decorator to register a tool handler."""

        def decorator(fn: Callable[..., str]) -> Callable[..., str]:
            self._tools[name] = ToolDef(
                name=name,
                description=description,
                parameters=parameters,
                handler=fn,
            )
            return fn

        return decorator

    def add(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable[..., str],
    ) -> None:
        """Register a tool directly (non-decorator)."""
        self._tools[name] = ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Convert all registered tools to OpenAI tools format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": td.name,
                    "description": td.description,
                    "parameters": td.parameters,
                },
            }
            for td in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any], cwd: str = ".") -> str:
        """Execute a tool by name. Returns result string."""
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'"

        tool = self._tools[name]
        try:
            result = tool.handler(cwd=cwd, **arguments)
            # Truncate very long results to avoid context explosion
            if len(result) > 50_000:
                result = result[:50_000] + f"\n... (truncated, {len(result)} total chars)"
            return result
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return f"Error: {type(e).__name__}: {e}"

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
