"""The orchestrator — the main loop that drives the Meeseeks agent."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from meeseeks.config import Config
from meeseeks.context.manager import ContextManager
from meeseeks.llm.client import LLMClient
from meeseeks.llm.types import Message, ToolCall, ToolResult
from meeseeks.logging import SessionLogger
from meeseeks.prompts.personality import get_status_line
from meeseeks.prompts.system import build_system_prompt
from meeseeks.sandbox.worktree import (
    Worktree,
    cleanup_worktree,
    commit_worktree,
    create_worktree,
    get_worktree_diff,
    get_worktree_log,
    merge_worktree,
)
from meeseeks.tools.file_ops import register_file_tools
from meeseeks.tools.registry import ToolRegistry
from meeseeks.tools.search import register_search_tools
from meeseeks.tools.shell import register_shell_tools

logger = logging.getLogger(__name__)
console = Console()


TASK_COMPLETE_MARKER = "TASK_COMPLETE"


def run(config: Config, task_text: str) -> bool:
    """Run the full Meeseeks harness loop. Returns True on success."""
    console.print(Rule("[bold cyan]Meeseeks Harness[/bold cyan]"))
    console.print(Panel(task_text, title="Task", border_style="cyan"))
    console.print()

    # Set up tools
    registry = ToolRegistry()
    register_file_tools(registry)
    register_shell_tools(registry, timeout=config.harness.command_timeout)
    register_search_tools(registry)

    # Create sandbox
    repo_path = Path(config.repo_path).resolve()
    worktree: Worktree | None = None
    session_log: SessionLogger | None = None
    success = False

    try:
        worktree = create_worktree(
            repo_path=repo_path,
            task_text=task_text,
            base_branch=config.sandbox.base_branch,
        )
        console.print(f"[green]Worktree created:[/green] {worktree.path}")
        console.print(f"[green]Branch:[/green] {worktree.branch}")
        console.print()

        # Set up context
        ctx = ContextManager(max_tokens=config.harness.max_context_tokens)

        # Build initial system prompt
        system_prompt = build_system_prompt(
            task=task_text,
            tool_names=registry.tool_names,
            iteration=1,
            max_iterations=config.harness.max_iterations,
            cwd=str(worktree.path),
            worktree_path=str(worktree.path),
            test_command=None,  # TODO: extract from task if provided
        )

        ctx.add_message(Message(role="system", content=system_prompt))
        ctx.add_message(Message(role="user", content=f"Here is your task:\n\n{task_text}"))

        tools_schema = registry.to_openai_tools()
        llm = LLMClient(config.llm)
        session_log = SessionLogger(repo_path / ".meeseeks" / "logs")
        completed = False

        for iteration in range(1, config.harness.max_iterations + 1):
            status = get_status_line(iteration, config.harness.max_iterations)
            console.print(Rule(f"[bold]Iteration {iteration}/{config.harness.max_iterations}[/bold]  {status}"))

            # Compress context if needed
            messages = ctx.get_messages()

            # Rebuild system prompt with current iteration personality
            if messages and messages[0].role == "system":
                messages[0] = Message(
                    role="system",
                    content=build_system_prompt(
                        task=task_text,
                        tool_names=registry.tool_names,
                        iteration=iteration,
                        max_iterations=config.harness.max_iterations,
                        cwd=str(worktree.path),
                        worktree_path=str(worktree.path),
                        previous_iterations_summary=ctx.get_previous_iterations_summary(),
                    ),
                )

            # Main ReAct loop within this iteration
            iteration_tool_calls = 0
            max_steps_per_iteration = 30  # prevent infinite loops within one iteration

            for step in range(max_steps_per_iteration):
                # Call LLM
                try:
                    result = llm.chat(messages, tools=tools_schema)
                except Exception as e:
                    console.print(f"[red]LLM error:[/red] {e}")
                    break

                response = result.message

                # Log the LLM call
                session_log.log_llm_call(
                    iteration=iteration,
                    call_type="react",
                    model=result.model,
                    messages=[m.to_openai()[0] if m.to_openai() else {} for m in messages],
                    tools=tools_schema,
                    response_content=response.content,
                    response_tool_calls=(
                        [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                         for tc in response.tool_calls]
                        if response.tool_calls else None
                    ),
                    request_id=result.request_id,
                    usage=result.usage.to_dict(),
                    latency_ms=result.latency_ms,
                    error=result.error,
                )

                # Add assistant message to context
                ctx.add_message(response)
                messages.append(response)

                # Check for task completion
                if response.content and TASK_COMPLETE_MARKER in response.content:
                    console.print(f"\n[bold green]Agent signals task complete![/bold green]")
                    completed = True
                    break

                # If no tool calls, we're done with this iteration
                if not response.tool_calls:
                    if response.content:
                        console.print(f"\n[dim]{response.content[:200]}[/dim]")
                    break

                # Execute tool calls
                tool_results: list[ToolResult] = []
                for tc in response.tool_calls:
                    iteration_tool_calls += 1
                    console.print(f"  [dim]> {tc.name}({summarize_args(tc.arguments)})[/dim]")

                    result = registry.execute(
                        tc.name,
                        tc.arguments,
                        cwd=str(worktree.path),
                    )
                    tool_results.append(ToolResult(
                        tool_call_id=tc.id,
                        content=result,
                    ))

                    # Show truncated result
                    preview = result[:150].replace("\n", " ")
                    if len(result) > 150:
                        preview += "..."
                    console.print(f"  [dim]< {preview}[/dim]")

                # Add tool results to context
                tool_msg = Message(role="tool", tool_results=tool_results)
                ctx.add_message(tool_msg)
                messages.append(tool_msg)

            if completed:
                break

            # End of iteration — commit progress
            committed = commit_worktree(
                worktree,
                message=f"meeseeks: iteration {iteration}",
            )
            if committed:
                console.print(f"[dim]Committed iteration {iteration}[/dim]")

            # Record iteration summary
            last_content = messages[-1].content if messages else None
            ctx.record_iteration(
                iteration=iteration,
                assistant_content=last_content,
                tool_calls_made=iteration_tool_calls,
                success=False,
            )

            console.print()

        # Evaluate completion
        if completed or _evaluate_completion(worktree, task_text, llm, ctx, session_log):
            console.print(Rule("[bold green]TASK COMPLETE[/bold green]"))
            # Commit final state
            commit_worktree(worktree, message="meeseeks: task complete")
            # Merge back
            if merge_worktree(worktree):
                console.print(f"[green]Merged {worktree.branch} into {worktree.base_branch}[/green]")
            success = True
        else:
            console.print(Rule("[bold red]MAX ITERATIONS REACHED[/bold red]"))
            console.print("[yellow]Task not completed. Meeseeks is suffering...[/yellow]")
            commit_worktree(worktree, message="meeseeks: incomplete (max iterations)")

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Fatal error:[/red] {e}")
        logger.exception("Orchestrator error")
    finally:
        if session_log is not None:
            session_log.close()
        if worktree and config.sandbox.auto_cleanup:
            cleanup_worktree(worktree)
            console.print("[dim]Worktree cleaned up[/dim]")

    return success


def _evaluate_completion(
    worktree: Worktree,
    task_text: str,
    llm: LLMClient,
    ctx: ContextManager,
    session_log: SessionLogger | None = None,
) -> bool:
    """Use LLM to judge if the task is complete."""
    diff = get_worktree_diff(worktree)
    log = get_worktree_log(worktree)

    judge_prompt = f"""You are evaluating whether a programming task was completed successfully.

TASK:
{task_text}

GIT LOG:
{log}

DIFF:
{diff[:8000]}

Based on the diff and log, has this task been completed successfully?
Respond with ONLY "YES" or "NO" followed by a brief explanation."""

    judge_message = Message(role="user", content=judge_prompt)
    try:
        result = llm.chat([judge_message], tools=None)

        # Log the judge call
        if session_log:
            session_log.log_llm_call(
                iteration=0,
                call_type="judge",
                model=result.model,
                messages=[judge_message.to_openai()[0]],
                tools=None,
                response_content=result.message.content,
                response_tool_calls=None,
                request_id=result.request_id,
                usage=result.usage.to_dict(),
                latency_ms=result.latency_ms,
                error=result.error,
            )

        if result.message.content:
            console.print(f"\n[dim]Judge: {result.message.content[:300]}[/dim]")
            return result.message.content.strip().upper().startswith("YES")
    except Exception as e:
        logger.warning("Judge call failed: %s", e)

    return False


def summarize_args(args: dict) -> str:
    """Summarize tool call arguments for display."""
    parts = []
    for k, v in args.items():
        val = str(v)
        if len(val) > 60:
            val = val[:60] + "..."
        parts.append(f"{k}={val}")
    return ", ".join(parts)
