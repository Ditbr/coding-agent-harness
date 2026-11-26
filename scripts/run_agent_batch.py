"""Run the coding agent on frozen SWE-bench tasks and export its predictions."""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from harness.agent.controller import AgentController
from harness.config import HarnessConfig
from harness.eval.models import EvalInstance, Prediction
from harness.eval.runner import load_instances_jsonl
from harness.events.schema import Event, EventType
from harness.events.stream import EventStream, JsonlTrajectoryLogger
from harness.llm.client import OpenAICompatibleClient
from harness.runtime.docker import DockerSandboxRuntime
from harness.tools.aci import build_default_tool_registry

ROOT = Path(__file__).resolve().parents[1]


def run_instance(
    instance: EvalInstance, llm: OpenAICompatibleClient, cfg: HarnessConfig, output: Path,
) -> tuple[Prediction, dict]:
    run_id = output.name
    trajectory = Path("trajectories") / f"{instance.instance_id}.jsonl"
    stream = EventStream()
    stream.subscribe(JsonlTrajectoryLogger(output / trajectory))
    start = time.monotonic()
    try:
        with DockerSandboxRuntime(
            image=instance.docker_image, config=cfg.sandbox,
            platform="linux/amd64", base_commit=instance.base_commit,
        ) as runtime:
            tools = build_default_tool_registry(runtime)
            controller = AgentController(llm, runtime, tools, stream, config=cfg)
            result = controller.run(instance.problem_statement, instance.instance_id, run_id=run_id)
        outcome = asdict(result)
        patch = outcome.pop("patch")
    except (RuntimeError, ValueError, OSError) as exc:
        events = stream.events
        if not events:
            stream.publish(Event(run_id, instance.instance_id, 0, EventType.TASK_STARTED))
        step = events[-1].step if events else 0
        stream.publish(Event(run_id, instance.instance_id, step, EventType.ERROR, {"message": str(exc)}))
        stream.publish(Event(run_id, instance.instance_id, step, EventType.TASK_FINISHED, {"status": "error"}))
        usage = [event.usage for event in events if event.usage is not None]
        outcome = {
            "run_id": run_id,
            "instance_id": instance.instance_id,
            "status": "error",
            "steps": step,
            "total_cost_usd": sum(item.cost_usd for item in usage),
            "total_prompt_tokens": sum(item.prompt_tokens for item in usage),
            "total_cached_tokens": sum(item.cached_tokens for item in usage),
            "total_completion_tokens": sum(item.completion_tokens for item in usage),
            "errors": [str(exc)],
        }
        patch = ""
    outcome.update(
        trajectory=str(trajectory), patch_chars=len(patch),
        seconds=round(time.monotonic() - start, 3),
    )
    return Prediction(instance.instance_id, cfg.llm.model, patch), outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/smoke_5.jsonl")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for predictions and trajectories")
    args = parser.parse_args()
    cfg = HarnessConfig.from_env()
    if cfg.llm.api_key in {"", "your-api-key-here"}:
        parser.error("Set LLM_API_KEY before running the agent")
    cfg.max_steps = min(cfg.max_steps, 20)
    cfg.max_cost_usd = min(cfg.max_cost_usd, 0.15)
    if cfg.max_steps <= 0 or cfg.max_cost_usd <= 0:
        parser.error("Agent budgets must be positive")

    instances = load_instances_jsonl(args.dataset)
    ids = {instance.instance_id for instance in instances}
    if not ids or len(ids) != len(instances):
        parser.error("Dataset must contain unique instance IDs")
    for instance in instances:
        if not re.fullmatch(r"[\w.-]+", instance.instance_id) or instance.instance_id in {".", ".."}:
            parser.error(f"Invalid instance ID {instance.instance_id!r}")
        if not instance.docker_image or not re.fullmatch(r"[0-9a-f]{40}", instance.base_commit):
            parser.error(f"{instance.instance_id} requires an image and a full Git base commit")

    output = args.output_dir
    output.mkdir(parents=True)
    llm = OpenAICompatibleClient(cfg.llm)
    errors = 0
    with (
        (output / "predictions.jsonl").open("w", encoding="utf-8") as predictions,
        (output / "results.jsonl").open("w", encoding="utf-8") as results,
    ):
        for instance in instances:
            prediction, outcome = run_instance(instance, llm, cfg, output)
            print(json.dumps(outcome, ensure_ascii=False), file=results, flush=True)
            print(json.dumps(prediction.to_dict(), ensure_ascii=False), file=predictions, flush=True)
            print(
                f"{instance.instance_id}: {outcome['status']}, {outcome['steps']} steps, "
                f"${outcome['total_cost_usd']:.6f}, {outcome['patch_chars']} patch chars",
                flush=True,
            )
            errors += outcome["status"] == "error"
    return int(errors > 0)


if __name__ == "__main__":
    raise SystemExit(main())
