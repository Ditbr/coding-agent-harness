"""OpenAI-compatible LLM gateway client with retry, caching metrics, and cost tracking."""

from __future__ import annotations

import http.client
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
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

    def __init__(self, config: LLMConfig, rpm_limit: int | None = None) -> None:
        self.config = config
        env_rpm = int(os.getenv("LLM_RPM_LIMIT", "0") or "0")
        self._rpm_limit = max(0, rpm_limit if rpm_limit is not None else env_rpm)
        self._rate_lock = threading.Lock()
        self._request_timestamps: deque[float] = deque()
        self._cooldown_until: float = 0.0

    def _wait_for_rate_slot(self, *, check_cooldown: bool = True) -> None:
        """Thread-safe sliding-window RPM pacer + shared 429 cooldown across workers."""
        while True:
            wait_seconds = 0.0
            with self._rate_lock:
                now = time.monotonic()
                if check_cooldown and now < self._cooldown_until:
                    wait_seconds = self._cooldown_until - now
                elif self._rpm_limit > 0:
                    window = 60.0
                    while self._request_timestamps and now - self._request_timestamps[0] >= window:
                        self._request_timestamps.popleft()
                    if len(self._request_timestamps) >= self._rpm_limit:
                        wait_seconds = (self._request_timestamps[0] + window) - now + 0.05
                    else:
                        min_gap = window / self._rpm_limit
                        if self._request_timestamps and (now - self._request_timestamps[-1]) < min_gap:
                            wait_seconds = (self._request_timestamps[-1] + min_gap) - now
                        else:
                            self._request_timestamps.append(now)
                            return
                else:
                    return
            if wait_seconds > 0:
                time.sleep(wait_seconds)
                check_cooldown = False

    def _note_response_rate_limit(self, headers: Any) -> None:
        """Auto-configure a safe RPM ceiling from gateway headers when LLM_RPM_LIMIT is unset."""
        if self._rpm_limit > 0 or not headers:
            return
        for key in (
            "x-ratelimit-api_key-limit-requests",
            "x-litellm-key-rpm-limit",
            "x-ratelimit-limit-requests",
        ):
            raw = headers.get(key)
            if raw and str(raw).isdigit():
                limit = int(raw)
                if 1 <= limit <= 600:
                    # Leave a small safety margin (e.g. 20 RPM -> 18 RPM) to avoid bursts hitting 429
                    safe_limit = max(1, limit - max(1, limit // 10))
                    with self._rate_lock:
                        if self._rpm_limit == 0:
                            self._rpm_limit = safe_limit
                    return

    @staticmethod
    def _parse_retry_after(exc: urllib.error.HTTPError) -> float | None:
        if not exc.headers:
            return None
        raw = exc.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(1.0, min(float(raw.strip()), 90.0))
        except ValueError:
            return None

    def _estimate_cost(self, prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> float:
        uncached_prompt = max(0, prompt_tokens - cached_tokens)
        cost = (
            (uncached_prompt / 1_000_000) * self.config.input_cost_per_1m_usd
            + (cached_tokens / 1_000_000) * self.config.cached_input_cost_per_1m_usd
            + (completion_tokens / 1_000_000) * self.config.output_cost_per_1m_usd
        )
        return cost

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
        if self.config.thinking:
            payload["thinking"] = {"type": self.config.thinking}

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        last_err: Exception | None = None
        max_attempts = max(self.config.max_retries, 1)
        rate_limit_max_attempts = max(max_attempts, 6)
        attempt = 0
        while True:
            attempt += 1
            self._wait_for_rate_slot(check_cooldown=(attempt == 1))
            start_ts = time.monotonic()
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            retry_delay: float | None = None
            is_rate_limit = False
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    self._note_response_rate_limit(getattr(resp, "headers", None))
                    data = json.loads(resp.read().decode("utf-8"))
                latency_ms = int((time.monotonic() - start_ts) * 1000)
                return self._parse_response(data, latency_ms)
            except urllib.error.HTTPError as exc:
                if exc.code not in {408, 429} and exc.code < 500:
                    raise RuntimeError(f"LLM gateway returned HTTP {exc.code}: {exc.reason}") from exc
                last_err = exc
                if exc.code == 429:
                    is_rate_limit = True
                    retry_after = self._parse_retry_after(exc)
                    backoff = retry_after if retry_after is not None else min(5.0 * (2 ** (attempt - 1)), 45.0)
                    retry_delay = backoff + random.uniform(0.2, 1.5)
                    with self._rate_lock:
                        self._cooldown_until = max(self._cooldown_until, time.monotonic() + retry_delay)
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
                last_err = exc

            allowed = rate_limit_max_attempts if is_rate_limit else max_attempts
            if attempt >= allowed:
                raise RuntimeError(f"LLM request failed after {attempt} attempts: {last_err}")
            time.sleep(retry_delay if retry_delay is not None else min(2**attempt, 8))

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
        cached_tokens = raw_usage.get("prompt_cache_hit_tokens")
        if cached_tokens is None:
            cached_tokens = prompt_details.get("cached_tokens")
        cached_tokens = min(prompt_tokens, max(0, int(cached_tokens or 0)))
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
