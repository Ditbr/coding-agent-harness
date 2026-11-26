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

        for step in range(1, self.config.max_steps + 1):
            steps_taken = step
            response = self.llm.chat(
                messages=self.context.build_messages(),
                tools=self.tools.schemas(),
            )
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
                status = "finished"
                summary = response.content.strip() or "Completed without further tool calls."
                break

            finished_flag = False
            loop_flag = False
            for tc in response.tool_calls:
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
                    obs = Observation(
                        tool=tc.name,
                        call_id=tc.call_id,
                        status="error",
                        content=f"Loop guardrail triggered: identical tool call repeated {k} times.",
                    )
                    self.context.add_observation(obs)
                    self.event_stream.publish(Event(
                        run_id=rid,
                        instance_id=instance_id,
                        step=step,
                        event_type=EventType.ERROR,
                        payload=obs.to_dict(),
                    ))
                    status = "loop_detected"
                    summary = obs.content
                    loop_flag = True
                    break

                obs = self.tools.execute(tc.name, tc.arguments, call_id=tc.call_id)
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
