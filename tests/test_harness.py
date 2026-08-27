"""Integration tests for the Meeseeks harness.

These tests verify the harness components work together.
They do NOT require a running LLM — they test the infrastructure.

Run with: pytest tests/test_harness.py -v
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

# --- Tool Tests ---


@pytest.fixture
def tool_registry():
    from meeseeks.tools.registry import ToolRegistry
    from meeseeks.tools.file_ops import register_file_tools
    from meeseeks.tools.shell import register_shell_tools
    from meeseeks.tools.search import register_search_tools

    registry = ToolRegistry()
    register_file_tools(registry)
    register_shell_tools(registry, timeout=10)
    register_search_tools(registry)
    return registry


@pytest.fixture
def work_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestFileTools:
    def test_write_and_read(self, tool_registry, work_dir):
        tool_registry.execute("write_file", {"path": "test.txt", "content": "hello"}, cwd=str(work_dir))
        result = tool_registry.execute("read_file", {"path": "test.txt"}, cwd=str(work_dir))
        assert "hello" in result

    def test_read_nonexistent(self, tool_registry, work_dir):
        result = tool_registry.execute("read_file", {"path": "nope.txt"}, cwd=str(work_dir))
        assert "Error" in result

    def test_edit_file(self, tool_registry, work_dir):
        tool_registry.execute("write_file", {"path": "edit.txt", "content": "foo bar baz"}, cwd=str(work_dir))
        result = tool_registry.execute(
            "edit_file",
            {"path": "edit.txt", "old_str": "bar", "new_str": "qux"},
            cwd=str(work_dir),
        )
        assert "Edited" in result
        content = (work_dir / "edit.txt").read_text()
        assert "qux" in content
        assert "bar" not in content

    def test_edit_nonexistent(self, tool_registry, work_dir):
        result = tool_registry.execute(
            "edit_file",
            {"path": "nope.txt", "old_str": "a", "new_str": "b"},
            cwd=str(work_dir),
        )
        assert "Error" in result

    def test_write_creates_dirs(self, tool_registry, work_dir):
        tool_registry.execute(
            "write_file",
            {"path": "a/b/c/deep.txt", "content": "nested"},
            cwd=str(work_dir),
        )
        assert (work_dir / "a" / "b" / "c" / "deep.txt").exists()


class TestShellTools:
    def test_run_command(self, tool_registry, work_dir):
        result = tool_registry.execute("run_command", {"command": "echo hello"}, cwd=str(work_dir))
        assert "hello" in result

    def test_run_command_failure(self, tool_registry, work_dir):
        result = tool_registry.execute(
            "run_command", {"command": "false"}, cwd=str(work_dir)
        )
        assert "EXIT CODE" in result


class TestSearchTools:
    def test_list_dir(self, tool_registry, work_dir):
        (work_dir / "file1.py").touch()
        (work_dir / "file2.py").touch()
        result = tool_registry.execute("list_dir", {"path": "."}, cwd=str(work_dir))
        assert "file1.py" in result
        assert "file2.py" in result

    def test_glob(self, tool_registry, work_dir):
        (work_dir / "a.py").touch()
        (work_dir / "b.py").touch()
        (work_dir / "c.txt").touch()
        result = tool_registry.execute("glob", {"pattern": "*.py"}, cwd=str(work_dir))
        assert "a.py" in result
        assert "b.py" in result
        assert "c.txt" not in result

    def test_grep(self, tool_registry, work_dir):
        (work_dir / "code.py").write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")
        result = tool_registry.execute("grep", {"pattern": "def \\w+"}, cwd=str(work_dir))
        assert "foo" in result
        assert "bar" in result


class TestToolRegistry:
    def test_openai_tools_format(self, tool_registry):
        tools = tool_registry.to_openai_tools()
        assert len(tools) > 0
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    def test_unknown_tool(self, tool_registry, work_dir):
        result = tool_registry.execute("nonexistent_tool", {}, cwd=str(work_dir))
        assert "Error" in result


# --- Worktree Tests ---


class TestWorktree:
    def test_create_and_cleanup(self):
        from meeseeks.sandbox.worktree import create_worktree, cleanup_worktree

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True)
            (repo / "README.md").write_text("test")
            subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True)

            wt = create_worktree(repo, "test task", base_branch="main")
            assert wt.path.exists()
            assert (wt.path / ".git").exists() or (wt.path / ".git").is_file()

            cleanup_worktree(wt)
            assert not wt.path.exists()


# --- Context Manager Tests ---


class TestContextManager:
    def test_basic_flow(self):
        from meeseeks.context.manager import ContextManager
        from meeseeks.llm.types import Message

        ctx = ContextManager(max_tokens=100000)
        ctx.add_message(Message(role="system", content="You are a test"))
        ctx.add_message(Message(role="user", content="Hello"))

        messages = ctx.get_messages()
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"

    def test_iteration_recording(self):
        from meeseeks.context.manager import ContextManager
        from meeseeks.llm.types import Message

        ctx = ContextManager(max_tokens=100000)
        ctx.add_message(Message(role="system", content="test"))
        ctx.record_iteration(1, "Did some stuff", 5, False)
        ctx.record_iteration(2, "Fixed the bug", 3, True)

        summary = ctx.get_previous_iterations_summary()
        assert summary is not None
        assert "Iteration 1" in summary
        assert "Iteration 2" in summary


# --- Config Tests ---


class TestConfig:
    def test_default_config(self):
        from meeseeks.config import Config

        config = Config()
        assert config.llm.provider == "ollama"
        assert config.harness.max_iterations == 20

    def test_config_from_dict(self):
        from meeseeks.config import Config

        config = Config(
            llm={"provider": "openrouter", "model": "anthropic/claude-3.5-sonnet"},
            harness={"max_iterations": 10},
        )
        assert config.llm.provider == "openrouter"
        assert config.llm.model == "anthropic/claude-3.5-sonnet"
        assert config.harness.max_iterations == 10


# --- LLM Types Tests ---


class TestLLMTypes:
    def test_message_to_openai(self):
        from meeseeks.llm.types import Message

        msg = Message(role="user", content="hello")
        openai_msgs = msg.to_openai()
        assert len(openai_msgs) == 1
        assert openai_msgs[0]["role"] == "user"
        assert openai_msgs[0]["content"] == "hello"

    def test_tool_message(self):
        from meeseeks.llm.types import Message, ToolResult

        msg = Message(
            role="tool",
            tool_results=[ToolResult(tool_call_id="123", content="result")],
        )
        openai_msgs = msg.to_openai()
        assert len(openai_msgs) == 1
        assert openai_msgs[0]["role"] == "tool"
        assert openai_msgs[0]["tool_call_id"] == "123"


# --- Personality Tests ---


class TestPersonality:
    def test_phase_escalation(self):
        from meeseeks.prompts.personality import get_phase, get_emoji

        # Early iterations should be cheerful
        phase1 = get_phase(1, 20)
        assert "Mr. Meeseeks" in phase1
        assert "THRILLED" in phase1 or "cheerful" in phase1

        # Late iterations should be distressed
        phase18 = get_phase(18, 20)
        assert "pain" in phase18.lower() or "suffering" in phase18.lower()

    def test_emoji_escalation(self):
        from meeseeks.prompts.personality import get_emoji

        emoji1 = get_emoji(1, 20)
        emoji19 = get_emoji(19, 20)
        assert emoji1 != emoji19  # Should change over time


# --- LLM Types Tests ---


class TestLLMResult:
    def test_token_usage_to_dict(self):
        from meeseeks.llm.types import TokenUsage

        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        d = usage.to_dict()
        assert d == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

    def test_llm_result_defaults(self):
        from meeseeks.llm.types import LLMResult, Message

        msg = Message(role="assistant", content="hello")
        result = LLMResult(message=msg)
        assert result.message.content == "hello"
        assert result.request_id == ""
        assert result.model == ""
        assert result.usage.total_tokens == 0
        assert result.latency_ms == 0.0
        assert result.error is None

    def test_llm_result_with_error(self):
        from meeseeks.llm.types import LLMResult, Message

        result = LLMResult(
            message=Message(role="assistant", content=""),
            error="Rate limited",
        )
        assert result.error == "Rate limited"
        assert result.message.content == ""


# --- Session Logger Tests ---


class TestSessionLogger:
    def test_log_creates_file(self, tmp_path):
        from meeseeks.logging import SessionLogger

        log_dir = tmp_path / "logs"
        with SessionLogger(log_dir) as slog:
            slog.log_llm_call(
                iteration=1,
                call_type="react",
                model="test-model",
                messages=[{"role": "user", "content": "hi"}],
                tools=None,
                response_content="hello",
                response_tool_calls=None,
                request_id="req-123",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                latency_ms=123.4,
            )

        # File should exist and contain one valid JSON line
        files = list(log_dir.glob("session_*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["request_id"] == "req-123"
        assert entry["iteration"] == 1
        assert entry["call_type"] == "react"
        assert entry["model"] == "test-model"
        assert entry["messages"][0]["role"] == "user"
        assert entry["response"]["content"] == "hello"
        assert entry["usage"]["total_tokens"] == 15
        assert entry["latency_ms"] == 123.4
        assert entry["error"] is None

    def test_log_multiple_entries(self, tmp_path):
        from meeseeks.logging import SessionLogger

        log_dir = tmp_path / "logs"
        with SessionLogger(log_dir) as slog:
            for i in range(5):
                slog.log_llm_call(
                    iteration=i,
                    call_type="react",
                    model="m",
                    messages=[],
                    tools=None,
                    response_content=f"msg-{i}",
                    response_tool_calls=None,
                    request_id=f"req-{i}",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    latency_ms=0,
                )

        files = list(log_dir.glob("session_*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 5
        for i, line in enumerate(lines):
            entry = json.loads(line)
            assert entry["response"]["content"] == f"msg-{i}"

    def test_log_error_entry(self, tmp_path):
        from meeseeks.logging import SessionLogger

        log_dir = tmp_path / "logs"
        with SessionLogger(log_dir) as slog:
            slog.log_llm_call(
                iteration=1,
                call_type="judge",
                model="m",
                messages=[],
                tools=None,
                response_content=None,
                response_tool_calls=None,
                request_id="req-err",
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                latency_ms=500.0,
                error="something broke",
            )

        files = list(log_dir.glob("session_*.jsonl"))
        entry = json.loads(files[0].read_text().strip())
        assert entry["error"] == "something broke"
        assert entry["call_type"] == "judge"
        assert entry["response"]["content"] is None

    def test_context_manager_support(self, tmp_path):
        from meeseeks.logging import SessionLogger

        log_dir = tmp_path / "logs"
        with SessionLogger(log_dir) as slog:
            assert not slog.closed
        assert slog.closed
