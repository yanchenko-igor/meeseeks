"""LLM client wrapping the OpenAI SDK for Ollama, OpenRouter, and NVIDIA."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator

from openai import OpenAI, RateLimitError, APIStatusError
from openai.types.chat import ChatCompletionChunk

from meeseeks.config import LLMConfig
from meeseeks.llm.types import LLMResult, Message, TokenUsage, ToolCall

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
    ) -> LLMResult:
        """Send a chat completion request. Returns an LLMResult with metadata."""
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

    def _call_with_retry(self, kwargs: dict[str, Any]) -> LLMResult:
        """Call with smart retry on transient errors.

        For rate limits:
        - Per-minute limits: wait until reset (usually seconds)
        - Daily/upstream limits: fail immediately — no point retrying for hours
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            start = time.monotonic()
            try:
                response = self._client.chat.completions.create(**kwargs)
                latency_ms = (time.monotonic() - start) * 1000

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

                usage = TokenUsage()
                if response.usage:
                    usage = TokenUsage(
                        prompt_tokens=response.usage.prompt_tokens or 0,
                        completion_tokens=response.usage.completion_tokens or 0,
                        total_tokens=response.usage.total_tokens or 0,
                    )

                return LLMResult(
                    message=Message(
                        role="assistant",
                        content=content,
                        tool_calls=tool_calls,
                    ),
                    request_id=response.id or "",
                    model=response.model or self.model,
                    usage=usage,
                    latency_ms=latency_ms,
                )
            except (RateLimitError, APIStatusError) as e:
                latency_ms = (time.monotonic() - start) * 1000
                last_error = e
                status = getattr(e, "status_code", 0)
                if status not in _RETRYABLE_STATUS and not isinstance(e, RateLimitError):
                    return LLMResult(
                        message=Message(role="assistant", content=""),
                        latency_ms=latency_ms,
                        error=str(e),
                    )

                # Parse rate limit headers to decide strategy
                headers = {}
                if hasattr(e, "response") and e.response is not None:
                    headers = dict(e.response.headers) if e.response.headers else {}

                reset_ts = headers.get("x-ratelimit-reset", "")
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
                    error_msg = (
                        f"Rate limited ({reason}). Reset in ~{minutes:.0f} min. "
                        f"Add credits or wait, then retry."
                    )
                    return LLMResult(
                        message=Message(role="assistant", content=""),
                        latency_ms=latency_ms,
                        error=error_msg,
                    )

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
            except Exception as e:
                latency_ms = (time.monotonic() - start) * 1000
                return LLMResult(
                    message=Message(role="assistant", content=""),
                    latency_ms=latency_ms,
                    error=str(e),
                )

        return LLMResult(
            message=Message(role="assistant", content=""),
            latency_ms=0,
            error=str(last_error) if last_error else "LLM call failed after retries",
        )

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

    def _stream_chat(self, kwargs: dict[str, Any]) -> LLMResult:
        """Stream a chat completion, collecting the full response."""
        kwargs["stream"] = True
        start = time.monotonic()
        stream: Iterator[ChatCompletionChunk] = (
            self._client.chat.completions.create(**kwargs)
        )

        content_parts: list[str] = []
        tool_calls_data: dict[int, dict[str, Any]] = {}
        last_chunk_model = ""
        stream_usage = TokenUsage()

        for chunk in stream:
            if not chunk.choices:
                # Usage info comes in the final chunk with no choices
                if hasattr(chunk, "usage") and chunk.usage:
                    stream_usage = TokenUsage(
                        prompt_tokens=getattr(chunk.usage, "prompt_tokens", 0) or 0,
                        completion_tokens=getattr(chunk.usage, "completion_tokens", 0) or 0,
                        total_tokens=getattr(chunk.usage, "total_tokens", 0) or 0,
                    )
                continue
            delta = chunk.choices[0].delta
            if chunk.model:
                last_chunk_model = chunk.model

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

        latency_ms = (time.monotonic() - start) * 1000

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
                for data in tool_calls_data.values()
            ]

        return LLMResult(
            message=Message(
                role="assistant",
                content="".join(content_parts) or None,
                tool_calls=tool_calls,
            ),
            model=last_chunk_model or self.model,
            usage=stream_usage,
            latency_ms=latency_ms,
        )
