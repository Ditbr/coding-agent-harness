"""ContextManager enforcing Prompt Caching prefix stability and Observation Masking."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from harness.config import ContextConfig
from harness.events.schema import Event, EventType, Observation
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
        self._compacted_size = 0
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
        if self.config.auto_compact:
            return [dict(message) for message in self._messages]
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

    def should_compact(self, tools: list[dict[str, Any]]) -> bool:
        if not self.config.auto_compact or len(self._messages) < 4:
            return False
        history_size = self._message_bytes(self._messages)
        framing = self._message_bytes([self._messages[:2], tools])
        threshold = max(self.config.compaction_trigger_tokens * 4, framing + 512)
        return history_size + self._message_bytes(tools) >= threshold and (
            history_size >= self._compacted_size + 512
        )

    @staticmethod
    def _message_bytes(messages: list) -> int:
        return len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))

    def summarize_progress(self, events: Sequence[Event], patch: str) -> str:
        paths = [line.removeprefix("+++ b/") for line in patch.splitlines() if line.startswith("+++ b/")]
        paths.extend(line.removeprefix("--- a/") for line in patch.splitlines() if line.startswith("--- a/"))
        actions = {event.payload.get("call_id"): event for event in events if event.event_type == EventType.ACTION}
        observations = [
            event for event in events
            if event.event_type == EventType.OBSERVATION or (
                event.event_type == EventType.ERROR and "tool" in event.payload
            )
        ]
        tests = [event for event in observations if event.payload.get("metadata", {}).get("test")
                 or event.payload.get("tool") == "run_command"]
        newest = {id(event) for event in observations[-8:] + tests[-3:]}
        report = ["Current modified files: " + (", ".join(sorted(set(paths))[:30]) or "(none)"),
                  "Observed attempts and tool output:"]
        for event in observations:
            if id(event) not in newest:
                continue
            tool = event.payload.get("tool", "")
            action = actions.get(event.payload.get("call_id"))
            args = dict(action.payload.get("args", {})) if action else {}
            if tool == "edit_file":
                args = {"path": args.get("path")}
            digest = " ".join(str(event.payload.get("content", "")).split())[:230]
            thought = " ".join(str(action.payload.get("thought", "")).split())[:90] if action else ""
            rationale = f" Tried because: {thought}" if thought else ""
            report.append(f"- Step {event.step} {tool} {str(args)[:120]} "
                          f"[{event.payload.get('status', '')}]: {digest}{rationale}")
        limit = max(256, min(5000, self.config.compaction_trigger_tokens * 2))
        summary = report[0][:limit // 3] + "\n" + "\n".join(report[1:])[-(limit * 2 // 3):]
        return summary

    def compact(self, structured_summary: str, original_task: str) -> None:
        """Reset bloated history into a clean structured working snapshot."""
        self._messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": original_task},
            {
                "role": "assistant",
                "content": f"[Context Compacted — Observed Working State]\n{structured_summary}",
            },
        ]
        if self.config.auto_compact:
            self.add_user_message("Continue the original task from the observed working state above.")
            self._compacted_size = self._message_bytes(self._messages)

    @property
    def raw_messages(self) -> list[dict[str, Any]]:
        return list(self._messages)
