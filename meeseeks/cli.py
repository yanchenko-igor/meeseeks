"""CLI entry point for the Meeseeks harness."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

from meeseeks.config import Config

load_dotenv()

console = Console()


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """Meeseeks — Autonomous agentic programming harness.

    I'm Mr. Meeseeks! Look at me!
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


@main.command()
@click.argument("task_file", type=click.Path(exists=True))
@click.option("--repo", "-r", type=click.Path(), default=".", help="Path to the git repository")
@click.option("--model", "-m", type=str, default=None, help="LLM model name")
@click.option("--provider", "-p", type=click.Choice(["ollama", "openrouter", "nvidia"]), default=None, help="LLM provider")
@click.option("--base-url", type=str, default=None, help="Override LLM API base URL")
@click.option("--max-iterations", "-n", type=int, default=None, help="Maximum iterations")
@click.option("--config-file", "-c", type=click.Path(exists=True), default=None, help="Config file path")
def run(
    task_file: str,
    repo: str,
    model: str | None,
    provider: str | None,
    base_url: str | None,
    max_iterations: int | None,
    config_file: str | None,
) -> None:
    """Run a task file through the Meeseeks harness.

    TASK_FILE is a plain text file describing what to build or fix.
    """
    # Load config
    config = Config.load(config_file)
    config.repo_path = repo
    config.task_file = task_file

    # Apply CLI overrides
    if model:
        config.llm.model = model
    if provider:
        config.llm.provider = provider
    if base_url:
        config.llm.base_url = base_url
    if max_iterations:
        config.harness.max_iterations = max_iterations

    # Read task
    task_text = Path(task_file).read_text(encoding="utf-8").strip()
    if not task_text:
        console.print("[red]Error: Task file is empty[/red]")
        sys.exit(1)

    # Validate repo
    repo_path = Path(config.repo_path).resolve()
    if not (repo_path / ".git").exists():
        console.print(f"[red]Error: {repo_path} is not a git repository[/red]")
        sys.exit(1)

    # Run
    from meeseeks.orchestrator import run as run_harness
    success = run_harness(config, task_text)

    sys.exit(0 if success else 1)


@main.command()
def init() -> None:
    """Initialize a .meeseeks.yaml config in the current directory."""
    config_path = Path(".meeseeks.yaml")
    if config_path.exists():
        console.print("[yellow].meeseeks.yaml already exists[/yellow]")
        return

    config_path.write_text(
        """# Meeseeks configuration
# See: https://github.com/your-repo/meeseeks

llm:
  provider: ollama
  model: llama3.1:8b
  # base_url: http://localhost:11434/v1
  # api_key: (or set OPENROUTER_API_KEY env var)

sandbox:
  worktree_dir: .meeseeks/worktrees
  auto_cleanup: true

harness:
  max_iterations: 20
  max_context_tokens: 32000
  command_timeout: 60
""",
        encoding="utf-8",
    )
    console.print("[green]Created .meeseeks.yaml[/green]")


if __name__ == "__main__":
    main()
