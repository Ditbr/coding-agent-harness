"""ContextManager enforcing Prompt Caching prefix stability and Observation Masking."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from harness.config import ContextConfig
from harness.events.schema import Event, EventType, Observation
from harness.llm.client import LLMResponse

DEFAULT_SYSTEM_PROMPT = """You are a senior repository-level software engineering agent.
Your job is to diagnose the true root cause of software issues or CI failures and apply a clean, minimal, complete fix.

Operating discipline:
1. Diagnose root cause, not surface symptoms: read the entire problem statement carefully; search for ALL related classes, subclasses, sibling methods, and callers before editing so you fix the underlying abstraction rather than patching only one caller.
2. Read efficiently: batch independent search_code and view_file calls in parallel in the same turn, and request generous line ranges (up to 300 lines) to avoid fragmented reading.
3. Reproduce and verify cleanly: run targeted reproduction snippets (`python -c ...`) and existing module test suites via run_command (in the foreground with an explicit timeout; never background tests or poll with sleep). Do NOT modify repository test files or changelogs unless explicitly asked.
4. Edit safely: use edit_file with unique surrounding context; verify AST/lint checks pass.
5. Verify thoroughly before calling finish: re-read every requirement and edge case in the problem statement, test all affected variants/types/subclasses, run the full existing test suite for the modified module(s), and inspect git_status_diff to ensure a minimal, clean diff with no leftover temporary files.
"""
ROOT_CAUSE = re.compile(
    r"(?:^|\n)\s*(?:\*\*|#+\s*)?(?:Confirmed root cause|Root cause)\s*(?:\*\*)?:\s*(?:\*\*)?([^\n]+)",
    re.IGNORECASE,
)


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
            # Keep standard replay fields (including reasoning_content for thinking models)
            # and drop non-standard gateway extras that can cause replay bloat or HTTP 400.
            sanitized = {
                key: response.raw_message[key]
                for key in ("role", "content", "tool_calls", "reasoning_content")
                if key in response.raw_message and response.raw_message[key] is not None
            }
            sanitized.setdefault("role", "assistant")
            if "content" not in sanitized:
                sanitized["content"] = response.content or ""
            self._messages.append(sanitized)
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
            tool_name = msg.get("name", "tool")
            never_mask = tool_name in {"edit_file", "git_status_diff"}
            if (
                idx in mask_set
                and not never_mask
                and len(msg.get("content", "")) > self.config.mask_threshold_chars
            ):
                masked = dict(msg)
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

    def estimated_request_tokens(self, tools: list[dict[str, Any]]) -> int:
        return (self._message_bytes(self._messages) + self._message_bytes(tools) + 3) // 4

    @staticmethod
    def _message_bytes(messages: list) -> int:
        return len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))

    def summarize_progress(self, events: Sequence[Event], patch: str) -> str:
        paths = sorted({
            line[6:].split("\t", 1)[0] for line in patch.splitlines() if line.startswith(("+++ b/", "--- a/"))
        })
        actions = {event.payload.get("call_id"): event for event in events if event.event_type == EventType.ACTION}
        observations = [
            event for event in events
            if event.event_type == EventType.OBSERVATION or (
                event.event_type == EventType.ERROR and "tool" in event.payload
            )
        ]
        root = "No confirmed root cause recorded. Recheck the strongest evidence against the task."
        for event in reversed(events):
            if event.event_type == EventType.LLM_RESPONSE and (
                cause := ROOT_CAUSE.search(event.payload.get("content") or "")
            ):
                root = f"Agent diagnosis at step {event.step}: {cause[1]}"
                break

        def describe(event: Event) -> str:
            tool = event.payload.get("tool", "")
            action = actions.get(event.payload.get("call_id"))
            args = dict(action.payload.get("args", {})) if action else {}
            if tool == "edit_file":
                args = {"path": args.get("path")}
            digest = " ".join(str(event.payload.get("content", "")).split())[:230]
            return f"- Step {event.step} {tool} {str(args)[:120]} [{event.payload.get('status', '')}]: {digest}"

        failed = [
            event for event in observations
            if event.payload.get("status") == "error" or event.payload.get("metadata", {}).get("test_result") == "failed"
        ]
        latest_checks = [
            event for event in observations if event.payload.get("tool") in {"run_test", "run_command"}
        ][-3:]
        edits = [
            event for event in observations
            if event.payload.get("tool") in {"edit_file", "rollback"} and event.payload.get("status") == "ok"
        ][-3:]
        limit = max(320, min(5000, self.config.compaction_trigger_tokens * 2))
        findings = "\n".join(map(describe, observations[-2:]))
        sections = [
            ("Confirmed root cause", f"{root}\n{findings}", limit // 5),
            ("Modified files and current state",
             "Current Git diff: " + (", ".join(paths[:30]) or "(none)") + "\n" + "\n".join(map(describe, edits)),
             limit // 4),
            ("Failed attempts", "\n".join(map(describe, failed[-5:])) or "No failed attempts recorded.", limit // 4),
            ("Next verification plan",
             "Inspect the current diff and run the focused reproduction and related regression tests. "
             "Use the previous outcomes below to avoid repeating failed attempts.\n"
             + "\n".join(map(describe, latest_checks)), limit * 3 // 10),
        ]
        return "\n\n".join(f"## {title}\n{body[:budget].rstrip()}" for title, body, budget in sections)

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
