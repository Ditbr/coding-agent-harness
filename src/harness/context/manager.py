"""ContextManager enforcing Prompt Caching prefix stability and Observation Masking."""

from __future__ import annotations

import json
from typing import Any

from harness.config import ContextConfig
from harness.events.schema import Observation
from harness.llm.client import LLMResponse


DEFAULT_SYSTEM_PROMPT = """You are a senior repository-level software engineering agent.
Your job is to diagnose and fix software issues or CI failures cleanly and minimally.

Operating discipline:
1. Reproduce first: locate or run a targeted test that reproduces the reported failure before editing code.
2. Read selectively: use search_code and windowed view_file instead of dumping huge outputs.
3. Edit safely: use edit_file with unique surrounding context; verify AST/lint checks pass.
4. Verify thoroughly: run both the failing reproduction test and related regression tests before calling finish.
5. Inspect git_status_diff before calling finish to ensure no temporary artifacts remain.
"""


class ContextManager:
    """Maintains an append-only conversation with non-destructive Observation Masking.

    Message layout is strictly ordered from static to dynamic for high Prompt Caching hit rates:
    1. Static system prompt (never mutated with timestamps or step counters)
    2. Initial task description (+ optional static repo map)
    3. Append-only assistant/tool trajectory
    """

    def __init__(
        self,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        config: ContextConfig | None = None,
    ) -> None:
        self.system_prompt = system_prompt
        self.config = config or ContextConfig()
        self._messages: list[dict[str, Any]] = [{"role": "system", "content": self.system_prompt}]

    def add_user_message(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_assistant_response(self, response: LLMResponse) -> None:
        if response.raw_message:
            self._messages.append(dict(response.raw_message))
            return
        msg: dict[str, Any] = {"role": "assistant", "content": response.content}
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in response.tool_calls
            ]
        self._messages.append(msg)

    def add_observation(self, obs: Observation) -> None:
        self._messages.append({
            "role": "tool",
            "tool_call_id": obs.call_id,
            "name": obs.tool,
            "content": obs.content,
        })

    def build_messages(self) -> list[dict[str, Any]]:
        """Return messages with old bulky tool outputs masked beyond keep_recent_observations."""
        tool_indices = [idx for idx, m in enumerate(self._messages) if m.get("role") == "tool"]
        keep = self.config.keep_recent_observations
        mask_set = set(tool_indices[:-keep]) if keep > 0 and len(tool_indices) > keep else set()

        rendered: list[dict[str, Any]] = []
        for idx, msg in enumerate(self._messages):
            if idx in mask_set and len(msg.get("content", "")) > self.config.mask_threshold_chars:
                masked = dict(msg)
                tool_name = msg.get("name", "tool")
                orig_len = len(msg["content"])
                first_line = msg["content"].splitlines()[0][:100] if msg["content"] else ""
                masked["content"] = (
                    f"[Observation masked: {tool_name} returned {orig_len} chars. "
                    f"Preview: {first_line!r}. Re-run tool if full details are needed.]"
                )
                rendered.append(masked)
            else:
                rendered.append(dict(msg))
        return rendered

    def compact(self, structured_summary: str, original_task: str) -> None:
        """Reset bloated history into a clean structured working snapshot."""
        self._messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": original_task},
            {
                "role": "assistant",
                "content": f"[Context Compacted — Verified Working State]\n{structured_summary}",
            },
        ]

    @property
    def raw_messages(self) -> list[dict[str, Any]]:
        return list(self._messages)
