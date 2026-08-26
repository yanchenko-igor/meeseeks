"""LLM client wrapping the OpenAI SDK for Ollama and OpenRouter."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

from openai import OpenAI, RateLimitError, APIStatusError
from openai.types.chat import ChatCompletionChunk

from meeseeks.config import LLMConfig
from meeseeks.llm.types import Message, ToolCall

logger = logging.getLogger(__name__)

# Transient errors worth retrying
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 8
_BASE_DELAY = 2.0


class LLMClient:
    def __init__(self, config: LLMConfig) -> None:
        self.config = config
        self.model = config.model
        self._client = OpenAI(
            base_url=config.resolve_base_url(),
            api_key=config.resolve_api_key(),
            timeout=config.timeout,
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Message:
        """Send a chat completion request. Returns an assistant Message."""
        openai_messages = []
        for msg in messages:
            openai_messages.extend(msg.to_openai())

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if tools:
            kwargs["tools"] = tools

        if stream:
            return self._stream_chat(kwargs)

        return self._call_with_retry(kwargs)
        content = choice.message.content or ""
        tool_calls: list[ToolCall] | None = None

        if choice.message.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                )
                for tc in choice.message.tool_calls
            ]

        return Message(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
        )

    def _call_with_retry(self, kwargs: dict[str, Any]) -> Message:
        """Call with smart retry on transient errors.

        For rate limits:
        - Per-minute limits: wait until reset (usually seconds)
        - Daily/upstream limits: fail immediately — no point retrying for hours
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                content = choice.message.content or ""
                tool_calls: list[ToolCall] | None = None

                if choice.message.tool_calls:
                    tool_calls = [
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=json.loads(tc.function.arguments),
                        )
                        for tc in choice.message.tool_calls
                    ]

                return Message(
                    role="assistant",
                    content=content,
                    tool_calls=tool_calls,
                )
            except (RateLimitError, APIStatusError) as e:
                last_error = e
                status = getattr(e, "status_code", 0)
                if status not in _RETRYABLE_STATUS and not isinstance(e, RateLimitError):
                    raise

                # Parse rate limit headers to decide strategy
                headers = {}
                if hasattr(e, "response") and e.response is not None:
                    headers = dict(e.response.headers) if e.response.headers else {}

                reset_ts = headers.get("x-ratelimit-reset", "")
                remaining = headers.get("x-ratelimit-remaining", "")
                limit_source = ""

                # Try to extract limit source from error body
                if hasattr(e, "body") and isinstance(e.body, dict):
                    meta = e.body.get("error", {}).get("metadata", {})
                    limit_source = meta.get("limit_source", "")

                # Decide: wait or bail
                wait_seconds = self._compute_wait(reset_ts, limit_source)

                if wait_seconds is None or wait_seconds > 600:
                    # Daily limit or unknown — don't waste time retrying
                    reason = limit_source or "rate_limit"
                    minutes = wait_seconds / 60 if wait_seconds else "unknown"
                    raise RuntimeError(
                        f"Rate limited ({reason}). Reset in ~{minutes:.0f} min. "
                        f"Add credits or wait, then retry."
                    ) from e

                if wait_seconds > 0:
                    logger.warning(
                        "Rate limited (%s), waiting %.0fs for reset...",
                        limit_source or "unknown", wait_seconds,
                    )
                    time.sleep(wait_seconds)
                else:
                    # Short per-minute limit — brief backoff
                    delay = min(_BASE_DELAY * (2 ** attempt), 30)
                    logger.warning(
                        "Rate limited (attempt %d), retrying in %.0fs...",
                        attempt + 1, delay,
                    )
                    time.sleep(delay)
            except Exception:
                raise

        raise last_error or RuntimeError("LLM call failed after retries")

    @staticmethod
    def _compute_wait(reset_ts: str, limit_source: str) -> float | None:
        """Compute wait time from rate limit headers. Returns seconds or None."""
        import time as _time

        if not reset_ts:
            return None

        try:
            # OpenRouter sends millisecond timestamps
            reset_float = float(reset_ts)
            if reset_float > 1e12:
                reset_float /= 1000.0
            wait = reset_float - _time.time()
            return max(0.0, wait)
        except (ValueError, TypeError):
            return None

    def _stream_chat(self, kwargs: dict[str, Any]) -> Message:
        """Stream a chat completion, collecting the full response."""
        kwargs["stream"] = True
        stream: Iterator[ChatCompletionChunk] = (
            self._client.chat.completions.create(**kwargs)
        )

        content_parts: list[str] = []
        tool_calls_data: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                content_parts.append(delta.content)
                print(delta.content, end="", flush=True)

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {
                            "id": tc_delta.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc_delta.id:
                        tool_calls_data[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_data[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_data[idx]["arguments"] += (
                                tc_delta.function.arguments
                            )

        if content_parts:
            print()  # newline after stream

        tool_calls: list[ToolCall] | None = None
        if tool_calls_data:
            tool_calls = [
                ToolCall(
                    id=data["id"],
                    name=data["name"],
                    arguments=json.loads(data["arguments"]) if data["arguments"] else {},
                )
                for data in sorted(tool_calls_data.values(), key=lambda x: x["id"])
            ]

        return Message(
            role="assistant",
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
        )
