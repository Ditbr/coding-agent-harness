"""AgentController: ReAct loop with budget ceilings, duplicate-action detection, and EventStream."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

from harness.config import HarnessConfig
from harness.context.manager import ContextManager
from harness.events.schema import Action, Event, EventType, Observation
from harness.events.stream import EventStream
from harness.llm.client import LLMClient
from harness.runtime.base import SandboxRuntime
from harness.tools.registry import ToolRegistry


@dataclass(slots=True)
class AgentRunResult:
    run_id: str
    instance_id: str
    status: str  # "finished" | "max_steps" | "budget_exceeded" | "loop_detected" | "error"
    summary: str
    patch: str
    steps: int
    total_cost_usd: float
    total_prompt_tokens: int
    total_cached_tokens: int
    total_completion_tokens: int
    errors: list[str] = field(default_factory=list)


class AgentController:
    """Orchestrates ContextManager, LLMClient, ToolRegistry, SandboxRuntime, and EventStream."""

    def __init__(
        self,
        llm: LLMClient,
        runtime: SandboxRuntime,
        tools: ToolRegistry,
        event_stream: EventStream | None = None,
        context: ContextManager | None = None,
        config: HarnessConfig | None = None,
    ) -> None:
        self.llm = llm
        self.runtime = runtime
        self.tools = tools
        self.event_stream = event_stream if event_stream is not None else EventStream()
        self.config = config if config is not None else HarnessConfig()
        self.context = context if context is not None else ContextManager(config=self.config.context)

    def _budget_notice(self, remaining_steps: int, had_successful_edit: bool) -> str:
        verifying = self.tools.has("run_test")
        if not 1 <= remaining_steps <= 5 or (not verifying and self.config.max_steps < 10):
            return ""
        message = f"Step budget notice: {remaining_steps} step(s) remaining"
        if verifying:
            try:
                if not self.runtime.git_diff().strip():
                    return (
                        f"\n\n[{message} and the working tree has no patch. Stop exploring. "
                        "Apply the smallest fix supported by your findings, then run a focused test.]"
                    )
            except (RuntimeError, OSError):
                pass
        elif not had_successful_edit:
            return (
                f"\n\n[{message} and no file edit has been applied yet. "
                "Stop exploring, apply your fix with edit_file, and run verification now.]"
            )
        return f"\n\n[{message}. Finish verifying your patch and call finish before reaching the step limit.]"

    def run(
        self,
        task_prompt: str,
        instance_id: str = "local",
        run_id: str | None = None,
        repo_map: str = "",
    ) -> AgentRunResult:
        rid = run_id or f"run_{uuid.uuid4().hex[:8]}"
        initial_user = task_prompt
        if repo_map:
            initial_user = f"{task_prompt}\n\n## Repository Map\n```text\n{repo_map}\n```"
        self.context.add_user_message(initial_user)

        self.event_stream.publish(Event(
            run_id=rid,
            instance_id=instance_id,
            step=0,
            event_type=EventType.TASK_STARTED,
            payload={"task_preview": task_prompt[:300]},
        ))

        total_cost = 0.0
        total_prompt = 0
        total_cached = 0
        total_completion = 0
        recent_signatures: list[str] = []
        status = "max_steps"
        summary = "Reached max_steps without calling finish."
        steps_taken = 0
        had_successful_edit = False
        recovered_signatures: dict[str, int] = {}
        tool_schemas = self.tools.schemas()

        for step in range(1, self.config.max_steps + 1):
            steps_taken = step
            if self.context.should_compact(tool_schemas):
                before = self.context.estimated_request_tokens(tool_schemas)
                snapshot = self.context.summarize_progress(self.event_stream.events, self.runtime.git_diff())
                self.context.compact(snapshot, initial_user)
                self.event_stream.publish(Event(
                    rid, instance_id, step, EventType.COMPACTION, {
                        "summary": snapshot,
                        "estimated_tokens_before": before,
                        "estimated_tokens_after": self.context.estimated_request_tokens(tool_schemas),
                    },
                ))
            response = self.llm.chat(messages=self.context.build_messages(), tools=tool_schemas)
            total_cost += response.usage.cost_usd
            total_prompt += response.usage.prompt_tokens
            total_cached += response.usage.cached_tokens
            total_completion += response.usage.completion_tokens

            self.context.add_assistant_response(response)
            self.event_stream.publish(Event(
                run_id=rid,
                instance_id=instance_id,
                step=step,
                event_type=EventType.LLM_RESPONSE,
                payload={
                    "content": response.content,
                    "tool_calls": [tc.to_dict() for tc in response.tool_calls],
                    "finish_reason": response.finish_reason,
                },
                usage=response.usage,
            ))

            if total_cost >= self.config.max_cost_usd:
                status = "budget_exceeded"
                summary = f"Stopped: cost ${total_cost:.4f} reached ceiling ${self.config.max_cost_usd:.4f}."
                break

            if not response.tool_calls:
                if response.finish_reason == "length":
                    nudge = (
                        "Your previous response hit the output token limit before emitting a tool call. "
                        "Keep your reasoning concise and emit your next tool call immediately."
                        + self._budget_notice(self.config.max_steps - step, had_successful_edit)
                    )
                    self.context.add_user_message(nudge)
                    self.event_stream.publish(Event(
                        rid, instance_id, step, EventType.ERROR,
                        {"message": "Truncated response (finish_reason=length) without tool calls; nudged to continue."},
                    ))
                    continue
                summary = response.content.strip() or "Completed without further tool calls."
                if self.tools.has("run_test"):
                    finish_check = self.tools.execute("finish", {"summary": summary})
                    if not finish_check.metadata.get("finished"):
                        finish_check.content += self._budget_notice(
                            self.config.max_steps - step, had_successful_edit,
                        )
                        self.context.add_user_message(finish_check.content)
                        self.event_stream.publish(Event(
                            rid, instance_id, step, EventType.ERROR, finish_check.to_dict(),
                        ))
                        continue
                status = "finished"
                break

            finished_flag = False
            loop_flag = False
            remaining_steps = self.config.max_steps - step
            num_calls = len(response.tool_calls)
            for tc_idx, tc in enumerate(response.tool_calls):
                action = Action(tool=tc.name, args=tc.arguments, call_id=tc.call_id, thought=response.content)
                self.event_stream.publish(Event(
                    run_id=rid,
                    instance_id=instance_id,
                    step=step,
                    event_type=EventType.ACTION,
                    payload=action.to_dict(),
                ))

                sig = f"{tc.name}:{json.dumps(tc.arguments, sort_keys=True, ensure_ascii=False)}"
                recent_signatures.append(sig)
                k = self.config.max_consecutive_duplicates
                if len(recent_signatures) >= k and len(set(recent_signatures[-k:])) == 1:
                    message = f"Loop guardrail triggered: identical tool call repeated {k} times."
                    recover = self.config.recover_tool_loops and recovered_signatures.get(sig, step) == step
                    if recover:
                        recovered_signatures[sig] = step
                        message += (
                            " This call was skipped. Inspect the previous observation and working tree, "
                            "then use a narrower search, new edit, different test, or a saved checkpoint."
                        )
                    obs = Observation(tc.name, "error", message, call_id=tc.call_id)
                    self.context.add_observation(obs)
                    self.event_stream.publish(Event(
                        run_id=rid,
                        instance_id=instance_id,
                        step=step,
                        event_type=EventType.ERROR,
                        payload=obs.to_dict(),
                    ))
                    if recover:
                        continue
                    status = "loop_detected"
                    summary = obs.content
                    loop_flag = True
                    break

                if "__parse_error__" in tc.arguments:
                    obs = Observation(
                        tool=tc.name,
                        status="error",
                        content=(
                            f"Tool call rejected ({tc.arguments['__parse_error__']}). "
                            "Re-emit this tool call with valid JSON arguments (keep edits concise if truncated)."
                        ),
                        call_id=tc.call_id,
                    )
                else:
                    obs = self.tools.execute(tc.name, tc.arguments, call_id=tc.call_id)
                if tc.name == "edit_file" and obs.status == "ok":
                    had_successful_edit = True
                if not obs.metadata.get("finished") and tc_idx == num_calls - 1:
                    obs.content += self._budget_notice(remaining_steps, had_successful_edit)
                self.context.add_observation(obs)
                self.event_stream.publish(Event(
                    run_id=rid,
                    instance_id=instance_id,
                    step=step,
                    event_type=EventType.OBSERVATION,
                    payload=obs.to_dict(),
                ))

                if obs.metadata.get("finished"):
                    status = "finished"
                    summary = str(obs.metadata.get("summary", ""))
                    finished_flag = True
                    break

            if finished_flag or loop_flag:
                break

        patch = self.runtime.git_diff()
        self.event_stream.publish(Event(
            run_id=rid,
            instance_id=instance_id,
            step=steps_taken,
            event_type=EventType.TASK_FINISHED,
            payload={"status": status, "summary": summary, "patch_chars": len(patch)},
        ))
        return AgentRunResult(
            run_id=rid,
            instance_id=instance_id,
            status=status,
            summary=summary,
            patch=patch,
            steps=steps_taken,
            total_cost_usd=round(total_cost, 6),
            total_prompt_tokens=total_prompt,
            total_cached_tokens=total_cached,
            total_completion_tokens=total_completion,
        )
