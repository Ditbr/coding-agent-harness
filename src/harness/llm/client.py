"""OpenAI-compatible LLM gateway client with retry, caching metrics, and cost tracking."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from harness.config import LLMConfig
from harness.events.schema import TokenUsage, ToolCallRequest


@dataclass(slots=True)
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    raw_message: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Send chat messages + optional tool schemas and return parsed LLMResponse."""


class OpenAICompatibleClient(LLMClient):
    """Zero-dependency client targeting OpenAI, DeepSeek, Qwen, or a custom LLM Gateway."""

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    def _estimate_cost(self, prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> float:
        uncached_prompt = max(0, prompt_tokens - cached_tokens)
        cost = (
            (uncached_prompt / 1_000_000) * self.config.input_cost_per_1m_usd
            + (cached_tokens / 1_000_000) * self.config.cached_input_cost_per_1m_usd
            + (completion_tokens / 1_000_000) * self.config.output_cost_per_1m_usd
        )
        return round(cost, 6)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        last_err: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            start_ts = time.monotonic()
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                latency_ms = int((time.monotonic() - start_ts) * 1000)
                return self._parse_response(data, latency_ms)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                last_err = exc
                if attempt < self.config.max_retries:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"LLM request failed after {self.config.max_retries} attempts: {last_err}")

    def _parse_response(self, data: dict[str, Any], latency_ms: int) -> LLMResponse:
        choice = data["choices"][0]
        msg = choice["message"]
        tool_calls: list[ToolCallRequest] = []
        for raw_tc in msg.get("tool_calls") or []:
            fn = raw_tc.get("function", {})
            raw_args = fn.get("arguments", "{}")
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            tool_calls.append(ToolCallRequest(
                call_id=raw_tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
            ))

        raw_usage = data.get("usage") or {}
        prompt_tokens = int(raw_usage.get("prompt_tokens", 0))
        completion_tokens = int(raw_usage.get("completion_tokens", 0))
        prompt_details = raw_usage.get("prompt_tokens_details") or {}
        cached_tokens = int(
            prompt_details.get("cached_tokens")
            or raw_usage.get("prompt_cache_hit_tokens")
            or 0
        )
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            cached_tokens=cached_tokens,
            completion_tokens=completion_tokens,
            cost_usd=self._estimate_cost(prompt_tokens, cached_tokens, completion_tokens),
            latency_ms=latency_ms,
        )
        return LLMResponse(
            content=msg.get("content") or "",
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.get("finish_reason") or "stop",
            raw_message=msg,
        )


class MockLLMClient(LLMClient):
    """Deterministic scripted LLM client for offline end-to-end tests."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append({"messages": list(messages), "tools": tools})
        if not self._responses:
            return LLMResponse(content="No scripted responses remaining.", finish_reason="stop")
        return self._responses.pop(0)
