"""Typed configuration dataclasses for the Coding Agent Harness."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class LLMConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    temperature: float = 0.0
    max_tokens: int = 8192
    timeout_seconds: int = 120
    max_retries: int = 3
    input_cost_per_1m_usd: float = 0.27
    cached_input_cost_per_1m_usd: float = 0.07
    output_cost_per_1m_usd: float = 1.10
    thinking: str = ""

    @classmethod
    def from_env(cls) -> LLMConfig:
        defaults = cls()
        usd_to_cny = float(os.getenv("LLM_USD_TO_CNY", "7.2"))

        def _rate(usd_var: str, cny_var: str, default: float) -> float:
            if usd_val := os.getenv(usd_var):
                return float(usd_val)
            if cny_val := os.getenv(cny_var):
                return float(cny_val) / usd_to_cny
            return default

        return cls(
            base_url=os.getenv("LLM_BASE_URL", defaults.base_url),
            api_key=os.getenv("LLM_API_KEY", ""),
            model=os.getenv("LLM_MODEL", defaults.model),
            temperature=float(os.getenv("LLM_TEMPERATURE", str(defaults.temperature))),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", str(defaults.max_tokens))),
            timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", str(defaults.timeout_seconds))),
            input_cost_per_1m_usd=_rate(
                "LLM_INPUT_COST_PER_1M_USD", "LLM_INPUT_COST_PER_1M_CNY", defaults.input_cost_per_1m_usd,
            ),
            cached_input_cost_per_1m_usd=_rate(
                "LLM_CACHED_INPUT_COST_PER_1M_USD",
                "LLM_CACHED_INPUT_COST_PER_1M_CNY",
                defaults.cached_input_cost_per_1m_usd,
            ),
            output_cost_per_1m_usd=_rate(
                "LLM_OUTPUT_COST_PER_1M_USD", "LLM_OUTPUT_COST_PER_1M_CNY", defaults.output_cost_per_1m_usd,
            ),
            thinking=os.getenv("LLM_THINKING", defaults.thinking),
        )


@dataclass(slots=True)
class SandboxConfig:
    backend: str = "local"  # "local" | "docker"
    docker_image: str = "python:3.11-slim"
    memory_limit: str = "2g"
    cpu_cores: float = 2.0
    pids_limit: int = 256
    network_disabled: bool = True
    cmd_timeout_seconds: int = 60
    max_output_chars: int = 8000
    pipefail: bool = True


@dataclass(slots=True)
class ContextConfig:
    keep_recent_observations: int = 16
    mask_threshold_chars: int = 3000
    compaction_trigger_tokens: int = 18_000
    repo_map_max_tokens: int = 1500
    auto_compact: bool = False


@dataclass(slots=True)
class HarnessConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    max_steps: int = 40
    max_cost_usd: float = 0.50
    max_consecutive_duplicates: int = 3
    recover_tool_loops: bool = False
    trajectories_dir: Path = field(default_factory=lambda: Path("trajectories"))

    @classmethod
    def from_env(cls) -> HarnessConfig:
        return cls(
            llm=LLMConfig.from_env(),
            sandbox=SandboxConfig(
                backend=os.getenv("SANDBOX_BACKEND", "local"),
                docker_image=os.getenv("SANDBOX_DOCKER_IMAGE", "python:3.11-slim"),
                memory_limit=os.getenv("SANDBOX_MEMORY_LIMIT", "2g"),
                cpu_cores=float(os.getenv("SANDBOX_CPU_CORES", "2.0")),
                pids_limit=int(os.getenv("SANDBOX_PIDS_LIMIT", "256")),
                cmd_timeout_seconds=int(os.getenv("SANDBOX_CMD_TIMEOUT", "60")),
            ),
            context=ContextConfig(
                keep_recent_observations=int(os.getenv("HARNESS_KEEP_RECENT_OBSERVATIONS", "16")),
                mask_threshold_chars=int(os.getenv("HARNESS_MASK_THRESHOLD_CHARS", "3000")),
            ),
            max_steps=int(os.getenv("HARNESS_MAX_STEPS", "40")),
            max_cost_usd=float(os.getenv("HARNESS_MAX_COST_USD", "0.50")),
            trajectories_dir=Path(os.getenv("HARNESS_TRAJECTORIES_DIR", "trajectories")),
        )
