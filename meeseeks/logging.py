"""Session logger — writes LLM request/response data to JSONL for training and debugging."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionLogger:
    """Append-only JSONL logger for LLM interactions.

    Writes one JSON object per line to a file named:
        .meeseeks/logs/session_<timestamp>.jsonl

    Each entry captures the full request, response, token usage, and latency
    for a single LLM call.
    """

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self._path = self._log_dir / f"session_{ts}.jsonl"
        self._file = open(self._path, "w", encoding="utf-8")
        self._entry_count = 0

        logger.info("Logging LLM calls to %s", self._path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def closed(self) -> bool:
        return self._file.closed

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def log_llm_call(
        self,
        *,
        iteration: int,
        call_type: str,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        response_content: str | None,
        response_tool_calls: list[dict[str, Any]] | None,
        request_id: str,
        usage: dict[str, int],
        latency_ms: float,
        error: str | None = None,
    ) -> None:
        """Write one LLM call entry to the JSONL log."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "iteration": iteration,
            "call_type": call_type,
            "model": model,
            "messages": messages,
            "tools": tools,
            "response": {
                "content": response_content,
                "tool_calls": response_tool_calls,
            },
            "usage": usage,
            "latency_ms": round(latency_ms, 1),
            "error": error,
        }

        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()
        self._entry_count += 1

    def close(self) -> None:
        """Flush and close the log file."""
        if self._file and not self._file.closed:
            try:
                self._file.flush()
            finally:
                self._file.close()
                logger.info(
                    "Session log closed: %d entries written to %s",
                    self._entry_count,
                    self._path,
                )

    def __enter__(self) -> SessionLogger:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
