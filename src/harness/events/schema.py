"""Typed event, action, observation, and usage schemas (OpenHands-inspired)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventType(str, Enum):
    TASK_STARTED = "task_started"
    LLM_RESPONSE = "llm_response"
    ACTION = "action"
    OBSERVATION = "observation"
    COMPACTION = "compaction"
    CHECKPOINT = "checkpoint"
    TASK_FINISHED = "task_finished"
    ERROR = "error"


@dataclass(slots=True)
class TokenUsage:
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolCallRequest:
    call_id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Action:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    thought: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Observation:
    tool: str
    status: str  # "ok" | "error"
    content: str
    call_id: str = ""
    truncated: bool = False
    exit_code: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def output_chars(self) -> int:
        return len(self.content)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["output_chars"] = self.output_chars
        return data


@dataclass(slots=True)
class Event:
    run_id: str
    instance_id: str
    step: int
    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    usage: TokenUsage | None = None
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "instance_id": self.instance_id,
            "step": self.step,
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "payload": self.payload,
            "usage": self.usage.to_dict() if self.usage else None,
        }
