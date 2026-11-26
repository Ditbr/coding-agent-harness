"""Tool specification, OpenAI-compatible JSON Schema export, and execution dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from harness.events.schema import Observation

ToolHandler = Callable[..., Observation]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Ordered, stable-prefix registry of orthogonal agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool registration: {spec.name}")
        self._tools[spec.name] = spec

    def schemas(self) -> list[dict[str, Any]]:
        """Return schemas in fixed registration order to preserve Prompt Caching prefix."""
        return [spec.to_openai_schema() for spec in self._tools.values()]

    def has(self, name: str) -> bool:
        return name in self._tools

    def execute(self, name: str, arguments: dict[str, Any], call_id: str = "") -> Observation:
        if name not in self._tools:
            available = ", ".join(self._tools.keys())
            return Observation(
                tool=name,
                call_id=call_id,
                status="error",
                content=f"Unknown tool '{name}'. Available tools: {available}",
            )
        spec = self._tools[name]
        try:
            obs = spec.handler(**arguments)
            obs.call_id = call_id
            return obs
        except TypeError as exc:
            return Observation(
                tool=name,
                call_id=call_id,
                status="error",
                content=f"Invalid arguments for '{name}': {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return Observation(
                tool=name,
                call_id=call_id,
                status="error",
                content=f"Tool '{name}' failed with {type(exc).__name__}: {exc}",
            )
