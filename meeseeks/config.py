"""Configuration management for Meeseeks harness."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class LLMConfig(BaseModel):
    provider: Literal["ollama", "openrouter", "nvidia"] = "ollama"
    model: str = "llama3.1:8b"
    base_url: str | None = None
    api_key: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 600.0

    def resolve_base_url(self) -> str:
        if self.base_url:
            return self.base_url
        if self.provider == "ollama":
            return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        if self.provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        if self.provider == "nvidia":
            return os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
        raise ValueError(f"Unknown provider: {self.provider}")

    def resolve_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.provider == "ollama":
            return os.getenv("OLLAMA_API_KEY", "ollama")
        if self.provider == "openrouter":
            key = os.getenv("OPENROUTER_API_KEY")
            if not key:
                raise ValueError(
                    "OPENROUTER_API_KEY environment variable required "
                    "when using openrouter provider"
                )
            return key
        if self.provider == "nvidia":
            key = os.getenv("NVIDIA_API_KEY")
            if not key:
                raise ValueError(
                    "NVIDIA_API_KEY environment variable required "
                    "when using nvidia provider"
                )
            return key
        raise ValueError(f"Unknown provider: {self.provider}")


class SandboxConfig(BaseModel):
    worktree_dir: str = ".meeseeks/worktrees"
    base_branch: str | None = None
    auto_cleanup: bool = True


class HarnessConfig(BaseModel):
    max_iterations: int = 20
    max_context_tokens: int = 32000
    command_timeout: int = 300
    completion_requires_tests: bool = True
    completion_requires_judge: bool = True
    judge_model: str | None = None


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    harness: HarnessConfig = Field(default_factory=HarnessConfig)
    repo_path: str = "."
    task_file: str | None = None

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> Config:
        data: dict = {}
        if config_path:
            path = Path(config_path)
            if path.exists():
                with open(path) as f:
                    data = yaml.safe_load(f) or {}

        # Check for .meeseeks.yaml in repo root
        repo_data: dict = {}
        repo_path = data.get("repo_path", ".")
        local_config = Path(repo_path) / ".meeseeks.yaml"
        if local_config.exists() and config_path is None:
            with open(local_config) as f:
                repo_data = yaml.safe_load(f) or {}

        merged = {**repo_data, **data}
        return cls(**merged)
