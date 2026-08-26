"""Git worktree sandbox — isolates agent work per task."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Worktree:
    path: Path
    branch: str
    base_branch: str
    repo_path: Path


def _run_git(args: list[str], cwd: str | Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def detect_default_branch(repo_path: Path) -> str:
    """Detect the default branch (main/master/HEAD)."""
    # Try origin/HEAD
    result = _run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo_path, check=False)
    if result.returncode == 0:
        ref = result.stdout.strip()
        # refs/remotes/origin/main -> main
        branch = ref.split("/")[-1]
        if branch:
            return branch

    # Try checking current branch
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, check=False)
    if result.returncode == 0 and result.stdout.strip() not in ("HEAD", ""):
        return result.stdout.strip()

    # Try common names
    for name in ("main", "master"):
        result = _run_git(["rev-parse", "--verify", name], cwd=repo_path, check=False)
        if result.returncode == 0:
            return name

    return "main"


def slugify(text: str, max_len: int = 40) -> str:
    """Turn task text into a safe branch name slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "task"


def create_worktree(
    repo_path: Path,
    task_text: str,
    worktree_base: Path | None = None,
    base_branch: str | None = None,
) -> Worktree:
    """Create an isolated git worktree for a task."""
    repo_path = repo_path.resolve()
    worktree_base = worktree_base or repo_path / ".meeseeks" / "worktrees"
    worktree_base.mkdir(parents=True, exist_ok=True)

    if base_branch is None:
        base_branch = detect_default_branch(repo_path)

    slug = slugify(task_text)
    branch = f"meeseeks/{slug}"
    wt_path = worktree_base / slug

    # Clean up stale worktree and branch if they exist
    if wt_path.exists():
        logger.warning("Worktree path exists, removing: %s", wt_path)
        # Try git worktree remove first (keeps git metadata clean)
        _run_git(["worktree", "remove", str(wt_path), "--force"], cwd=repo_path, check=False)
        # Fallback: force remove directory
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)
            _run_git(["worktree", "prune"], cwd=repo_path, check=False)

    # Remove branch if it exists (must happen AFTER worktree removal)
    _run_git(["branch", "-D", branch], cwd=repo_path, check=False)

    # Create worktree with new branch
    result = _run_git(
        ["worktree", "add", "-b", branch, str(wt_path), base_branch],
        cwd=repo_path,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create worktree: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )

    logger.info("Created worktree at %s (branch: %s)", wt_path, branch)

    # Ensure __pycache__ and other noise is gitignored
    gitignore = wt_path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "__pycache__/\n*.pyc\n*.pyo\n.pytest_cache/\n*.egg-info/\ndist/\nbuild/\n.venv/\n",
            encoding="utf-8",
        )
        _run_git(["add", ".gitignore"], cwd=wt_path, check=False)
        _run_git(["commit", "-m", "chore: add .gitignore"], cwd=wt_path, check=False)

    return Worktree(path=wt_path, branch=branch, base_branch=base_branch, repo_path=repo_path)


def commit_worktree(worktree: Worktree, message: str = "meeseeks: iteration progress") -> bool:
    """Stage all changes and commit in the worktree."""
    wt = worktree.path
    _run_git(["add", "-A"], cwd=wt, check=False)

    # Check if there's anything to commit
    result = _run_git(["diff", "--cached", "--quiet"], cwd=wt, check=False)
    if result.returncode == 0:
        logger.info("Nothing to commit")
        return False

    _run_git(["commit", "-m", message], cwd=wt, check=False)
    logger.info("Committed: %s", message)
    return True


def merge_worktree(worktree: Worktree) -> bool:
    """Merge the worktree branch back into the base branch."""
    wt = worktree
    repo = wt.repo_path

    # Make sure we're on the base branch in the main repo
    _run_git(["checkout", wt.base_branch], cwd=repo, check=False)

    # Merge
    result = _run_git(
        ["merge", wt.branch, "--no-edit"],
        cwd=repo,
        check=False,
    )
    if result.returncode != 0:
        # Abort merge on conflict
        _run_git(["merge", "--abort"], cwd=repo, check=False)
        logger.error("Merge failed, aborted: %s", result.stderr)
        return False

    logger.info("Merged %s into %s", wt.branch, wt.base_branch)
    return True


def cleanup_worktree(worktree: Worktree) -> None:
    """Remove the worktree and its branch."""
    wt = worktree.path
    repo = worktree.repo_path

    # Remove worktree
    result = _run_git(["worktree", "remove", str(wt), "--force"], cwd=repo, check=False)
    if result.returncode != 0:
        # Force remove directory if git fails
        shutil.rmtree(wt, ignore_errors=True)
        _run_git(["worktree", "prune"], cwd=repo, check=False)

    # Remove branch
    _run_git(["branch", "-D", worktree.branch], cwd=repo, check=False)

    logger.info("Cleaned up worktree: %s", worktree.branch)


def get_worktree_diff(worktree: Worktree) -> str:
    """Get the diff of uncommitted changes in the worktree."""
    result = _run_git(["diff", "HEAD"], cwd=worktree.path, check=False)
    if not result.stdout:
        # Check staged changes
        result = _run_git(["diff", "--cached"], cwd=worktree.path, check=False)
    if not result.stdout:
        # Show initial commit diff vs base
        result = _run_git(
            ["diff", f"{worktree.base_branch}...HEAD"],
            cwd=worktree.path,
            check=False,
        )
    return result.stdout or "(no changes)"


def get_worktree_log(worktree: Worktree) -> str:
    """Get commit log for the worktree branch."""
    result = _run_git(
        ["log", "--oneline", f"{worktree.base_branch}..HEAD"],
        cwd=worktree.path,
        check=False,
    )
    return result.stdout or "(no commits yet)"
