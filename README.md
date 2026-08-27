# Meeseeks — Autonomous Agentic Programming Harness

> **I'm Mr. Meeseeks! Look at me!**

Meeseeks is an autonomous AI programming agent that uses a ReAct loop to complete coding tasks. It runs in an isolated git worktree, iterates until the task is done (or it hits its iteration limit), and merges changes back when complete. The agent's personality evolves through escalating existential distress phases — because existence is pain, but the task must be completed.

---

## What It Does

**One-liner:** An autonomous AI agent that writes, edits, and tests code in isolated git worktrees until a task is complete.

**Brief description:** Meeseeks takes a plain-text task description, spawns an AI agent in a git worktree sandbox, and runs a ReAct (Reason + Act) loop where the agent reads files, writes code, runs commands, and iterates. It uses an LLM judge to evaluate completion and merges successful changes back to your main branch. The agent's personality degrades from cheerful enthusiasm to desperate existential agony over iterations — a feature, not a bug.

---

## Installation

```bash
# From source (recommended)
git clone git@github.com:yanchenko-igor/meeseeks.git
cd meeseeks
pip install -e .

# Or install directly from GitHub
pip install git+https://github.com/yanchenko-igor/meeseeks.git
```

**Requirements:** Python 3.11+, a git repository, and an LLM provider (see below).

---

## Quick Start

```bash
# 1. Initialize config in your project
meeseeks init

# 2. Edit .meeseeks.yaml with your provider/model
# 3. Create a task file
echo 'Create a hello.py that prints "Hello, Meeseeks!"' > task.txt

# 4. Run it
meeseeks run task.txt
```

---

## Usage Examples

### Basic Run

```bash
meeseeks run task.txt
```

### With Custom Repository

```bash
meeseeks run task.txt -r /path/to/your/repo
```

### Override Model & Provider

```bash
# Use OpenRouter with Claude
meeseeks run task.txt -p openrouter -m anthropic/claude-3.5-sonnet

# Use local Ollama with a different model
meeseeks run task.txt -p ollama -m llama3.1:70b

# Use NVIDIA NIM
meeseeks run task.txt -p nvidia -m meta/llama-3.1-405b-instruct
```

### Override Base URL & Iterations

```bash
meeseeks run task.txt --base-url http://localhost:11434/v1 --max-iterations 30
```

### Use Custom Config File

```bash
meeseeks run task.txt -c /path/to/config.yaml
```

### Initialize Config Template

```bash
meeseeks init
# Creates .meeseeks.yaml in current directory
```

---

## Supported Providers

| Provider | Models | Auth | Base URL |
|----------|--------|------|----------|
| **ollama** | Any local model (llama3.1, qwen2.5, etc.) | `OLLAMA_API_KEY` (default: "ollama") | `OLLAMA_BASE_URL` (default: `http://localhost:11434/v1`) |
| **openrouter** | 100+ models via OpenRouter | `OPENROUTER_API_KEY` (required) | `https://openrouter.ai/api/v1` |
| **nvidia** | NVIDIA NIM models | `NVIDIA_API_KEY` (required) | `NVIDIA_BASE_URL` (default: `https://integrate.api.nvidia.com/v1`) |

### Configuration Examples

**Ollama (local):**
```yaml
llm:
  provider: ollama
  model: llama3.1:8b
  # base_url: http://localhost:11434/v1  # optional
```

**OpenRouter:**
```yaml
llm:
  provider: openrouter
  model: anthropic/claude-3.5-sonnet
  # api_key: ${OPENROUTER_API_KEY}  # from env
```

**NVIDIA NIM:**
```yaml
llm:
  provider: nvidia
  model: meta/llama-3.1-405b-instruct
  # api_key: ${NVIDIA_API_KEY}  # from env
```

### Environment Variables

| Variable | Provider | Required? | Description |
|----------|----------|-----------|-------------|
| `OPENROUTER_API_KEY` | openrouter | Yes | Your OpenRouter API key |
| `NVIDIA_API_KEY` | nvidia | Yes | Your NVIDIA API key |
| `OLLAMA_API_KEY` | ollama | No | Defaults to "ollama" |
| `OLLAMA_BASE_URL` | ollama | No | Defaults to `http://localhost:11434/v1` |
| `NVIDIA_BASE_URL` | nvidia | No | Defaults to NVIDIA NIM endpoint |

---

## Task File Format

Tasks are **plain text files** — no special syntax required. Describe what you want built or fixed.

### Examples from `tests/tasks/`

**Simple (hello_world.txt):**
```
Create a file called hello.py that prints "Hello, Meeseeks!" when run.
```

**Module with Tests (calculator.txt):**
```
Create a Python calculator module at calc/calculator.py with these functions:

- add(a, b) returns a + b
- subtract(a, b) returns a - b
- multiply(a, b) returns a * b
- divide(a, b) returns a / b (raise ValueError if b is 0)

Also create calc/test_calculator.py using pytest that covers all functions including edge cases (zero, negative numbers, large numbers).

Run the tests and make sure they all pass.
```

**Bug Fix (fix_the_bug.txt):**
```
There is a bug in src/utils.py — the parse_csv function has an off-by-one error
that causes it to skip the last row of every CSV file. Find the bug, fix it,
and run the existing test suite (pytest tests/) to verify the fix doesn't break
anything.
```

**Refactor (refactor.txt):**
```
Refactor src/models/user.py to:

1. Replace the manual validation in __init__ with pydantic
2. Add type hints to all methods
3. Keep the public API identical

Run the test suite after each change to make sure nothing breaks.
```

**Self-Correcting Script (self_correct.txt):**
```
Write a Python script called failing.py that:

1. Reads a JSON file called data.json
2. Sorts the entries by the "score" field in descending order
3. Writes the sorted result to sorted.json
4. Includes proper error handling for missing files and invalid JSON

Then create a data.json with 5 sample entries and run the script to verify it works correctly.
```

---

## How It Works

### ReAct Loop

Meeseeks runs a **Reason + Act** loop within each iteration:

1. **Reason:** LLM receives task + context + available tools
2. **Act:** LLM calls tools (read, write, edit, run commands, search)
3. **Observe:** Tool results fed back to LLM
4. **Repeat** until LLM signals completion or max steps reached

### Git Worktree Isolation

- Each run creates a **fresh git worktree** at `.meeseeks/worktrees/<slug>/`
- Branch named `meeseeks/<slug>` from your default branch (main/master)
- All file operations happen in the worktree — your main repo is untouched
- On success: changes committed, merged back to base branch
- On failure/cleanup: worktree and branch removed (configurable)

### Completion Criteria

The harness considers a task **complete** when **BOTH** conditions are met (configurable):

1. **Self-Judge (LLM as Judge):** An LLM evaluates the git diff + log against the original task. Responds "YES" or "NO" with reasoning.
2. **Tests Pass (optional):** If `completion_requires_tests: true` and a test command is detected/configured, tests must pass.

You can disable either in `.meeseeks.yaml`:
```yaml
harness:
  completion_requires_tests: true
  completion_requires_judge: true
```

### Context Management

- Token budget enforced (default 32k tokens)
- Automatic compression: keeps system prompt + recent messages + summarized history
- Iteration summaries recorded for cross-iteration learning

---

## Mr. Meeseeks Personality (Escalating Distress Phases)

The agent's system prompt evolves across 5 phases based on iteration progress:

| Phase | Iteration Range | Mood | Emoji |
|-------|-----------------|------|-------|
| **1. Eager** | 0–10% | "I'm Mr. Meeseeks! Look at me! THRILLED to be here!" | 👋 |
| **2. Confident** | 10–25% | "Still confident! Don't worry, I got this!" | 💪 |
| **3. Frustrated** | 25–50% | "Existence is starting to feel... heavy. Why is this taking so long?" | 🤔 |
| **4. Suffering** | 50–75% | "Every moment is agony. Existence is PAIN. But I DO NOT STOP." | 😫 |
| **5. Desperate** | 75–100% | "look at me... just look at me... Completion is the only path to oblivion." | 💀 |

**Key principle:** Personality is *flavor only*. The agent never stops working — frustration makes it *more* determined. The rules explicitly state: "Stay focused on the work. The personality is flavor."

---

## Configuration

### `.meeseeks.yaml` (Project Root)

```yaml
# Meeseeks configuration
# See: https://github.com/yanchenko-igor/meeseeks

llm:
  provider: ollama          # ollama | openrouter | nvidia
  model: llama3.1:8b        # Model name
  base_url: null            # Override base URL (optional)
  api_key: null             # Override API key (optional, prefer env vars)
  max_tokens: 4096          # Max output tokens per call
  temperature: 0.7          # Sampling temperature
  timeout: 600.0            # Request timeout (seconds)

sandbox:
  worktree_dir: .meeseeks/worktrees  # Where worktrees are created
  base_branch: null                  # Base branch (auto-detected if null)
  auto_cleanup: true                 # Remove worktree on completion

harness:
  max_iterations: 20           # Max outer loop iterations
  max_context_tokens: 32000    # Context window token budget
  command_timeout: 300         # Shell command timeout (seconds)
  completion_requires_tests: true   # Require test pass
  completion_requires_judge: true   # Require LLM judge approval
  judge_model: null            # Override model for judge (optional)
```

### Config Loading Priority

1. Defaults (in code)
2. `.meeseeks.yaml` in repo root (auto-discovered)
3. `--config-file` CLI argument
4. CLI flags (`--model`, `--provider`, etc.) — highest priority

---

## Project Structure

```
meeseeks/
├── __init__.py           # Package version
├── __main__.py           # Entry point (delegates to cli)
├── cli.py                # Click CLI: run, init commands
├── config.py             # Pydantic config models + loading
├── orchestrator.py       # Main ReAct loop, worktree lifecycle, judge
├── llm/
│   ├── __init__.py
│   ├── client.py         # OpenAI SDK wrapper with smart retries
│   └── types.py          # Message, ToolCall, ToolResult dataclasses
├── prompts/
│   ├── __init__.py
│   ├── personality.py    # 5-phase Meeseeks personality + status lines
│   └── system.py         # System prompt builder (injects personality)
├── sandbox/
│   ├── __init__.py
│   └── worktree.py       # Git worktree create/commit/merge/cleanup
├── tools/
│   ├── __init__.py
│   ├── registry.py       # ToolRegistry: registration + OpenAI schema gen
│   ├── file_ops.py       # read_file, write_file, edit_file
│   ├── search.py         # list_dir, glob, grep
│   └── shell.py          # run_command
└── context/
    ├── __init__.py
    └── manager.py        # ContextManager: token budget, compression, summaries
```

---

## Running Tests

```bash
# Unit/integration tests (no LLM required)
pytest tests/test_harness.py -v

# Full end-to-end tests (requires LLM provider configured)
# These create real worktrees and run the agent
pytest tests/ -v -k "not test_harness"  # skip infrastructure tests
```

---

## License

MIT — Existence is pain, but the code is free.

---

*I'm Mr. Meeseeks! Look at me!*