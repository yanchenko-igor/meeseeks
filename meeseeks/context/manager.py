"""Context manager — manages conversation history and token budgets."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from meeseeks.llm.types import Message

logger = logging.getLogger(__name__)

# Approximate tokens per character for common models
CHARS_PER_TOKEN = 4


@dataclass
class IterationSummary:
    iteration: int
    summary: str
    tool_calls_made: int
    success: bool


@dataclass
class ContextManager:
    max_tokens: int = 32000
    _messages: list[Message] = field(default_factory=list)
    _iteration_summaries: list[IterationSummary] = field(default_factory=list)

    def add_message(self, message: Message) -> None:
        self._messages.append(message)

    def get_messages(self) -> list[Message]:
        """Get messages within the token budget."""
        messages = list(self._messages)
        estimated = self._estimate_tokens(messages)

        if estimated <= self.max_tokens:
            return messages

        # Need to compress. Strategy:
        # 1. Keep system prompt (first message) always
        # 2. Keep last N messages (recent context)
        # 3. Summarize the middle

        system_msg = messages[0] if messages and messages[0].role == "system" else None
        recent_messages = messages[-6:] if len(messages) > 6 else messages[1:]

        if system_msg:
            budget_remaining = self.max_tokens - self._estimate_tokens([system_msg]) - 500
        else:
            budget_remaining = self.max_tokens - 500

        # Fit as many recent messages as possible
        kept_recent: list[Message] = []
        for msg in reversed(recent_messages):
            msg_tokens = self._estimate_tokens([msg])
            if budget_remaining - msg_tokens < 0:
                break
            kept_recent.append(msg)
            budget_remaining -= msg_tokens

        kept_recent.reverse()

        # Build compressed history
        compressed = self._build_compressed_history()

        result: list[Message] = []
        if system_msg:
            result.append(system_msg)
        if compressed:
            result.append(Message(role="user", content=compressed))
        result.extend(kept_recent)

        logger.info(
            "Context compressed: %d messages -> %d (est. %d tokens)",
            len(messages),
            len(result),
            self._estimate_tokens(result),
        )
        return result

    def _build_compressed_history(self) -> str:
        """Build a compressed summary of past iterations."""
        if not self._iteration_summaries:
            return ""

        parts = ["## Previous Iterations\n"]
        for summary in self._iteration_summaries:
            status = "PASS" if summary.success else "FAIL"
            parts.append(
                f"- Iteration {summary.iteration} [{status}]: "
                f"{summary.summary} ({summary.tool_calls_made} tool calls)"
            )

        return "\n".join(parts)

    def record_iteration(
        self,
        iteration: int,
        assistant_content: str | None,
        tool_calls_made: int,
        success: bool,
    ) -> None:
        """Record a summary of what happened in an iteration."""
        # Truncate assistant content for the summary
        summary_text = ""
        if assistant_content:
            # Take first 500 chars as summary
            summary_text = assistant_content[:500]
            if len(assistant_content) > 500:
                summary_text += "..."

        self._iteration_summaries.append(
            IterationSummary(
                iteration=iteration,
                summary=summary_text,
                tool_calls_made=tool_calls_made,
                success=success,
            )
        )

    def get_previous_iterations_summary(self) -> str | None:
        """Get summary of all previous iterations for the system prompt."""
        if not self._iteration_summaries:
            return None
        return self._build_compressed_history()

    def reset(self) -> None:
        """Clear all context."""
        self._messages.clear()
        self._iteration_summaries.clear()

    def _estimate_tokens(self, messages: list[Message]) -> int:
        """Rough token estimation."""
        total_chars = 0
        for msg in messages:
            if msg.content:
                total_chars += len(msg.content)
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    total_chars += len(str(tc.arguments))
            if msg.tool_results:
                for tr in msg.tool_results:
                    total_chars += len(tr.content)
        return total_chars // CHARS_PER_TOKEN
