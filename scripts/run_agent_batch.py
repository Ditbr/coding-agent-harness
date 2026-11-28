"""Run the coding agent on frozen SWE-bench tasks and export its predictions."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from harness.agent.controller import AgentController
from harness.config import HarnessConfig
from harness.eval.artifacts import atomic_write, input_fingerprint, write_json
from harness.eval.models import EvalInstance, Prediction
from harness.eval.runner import load_instances_jsonl, read_jsonl
from harness.events.schema import Event, EventType
from harness.events.stream import EventStream, JsonlTrajectoryLogger
from harness.llm.client import OpenAICompatibleClient
from harness.repomap.mapper import RepoMapper
from harness.runtime.docker import DockerSandboxRuntime
from harness.tools.aci import build_default_tool_registry

ROOT = Path(__file__).resolve().parents[1]


def run_instance(
    instance: EvalInstance, llm: OpenAICompatibleClient, cfg: HarnessConfig, output: Path,
    with_repomap: bool = False, with_verification: bool = False,
) -> tuple[Prediction, dict]:
    run_id = output.name
    trajectory = Path("trajectories") / f"{instance.instance_id}.jsonl"
    if (output / trajectory).exists():
        trajectory = trajectory.with_stem(f"{trajectory.stem}-{uuid4().hex[:8]}")
    stream = EventStream()
    stream.subscribe(JsonlTrajectoryLogger(output / trajectory))
    start = time.monotonic()
    try:
        with DockerSandboxRuntime(
            image=instance.docker_image, config=cfg.sandbox,
            platform="linux/amd64", base_commit=instance.base_commit,
        ) as runtime:
            tools = build_default_tool_registry(
                runtime, verification_modules=instance.test_modules if with_verification else None,
                enable_checkpoints=cfg.recover_tool_loops or with_verification, repo=instance.repo,
            )
            repo_map = (
                RepoMapper(runtime).build_ranked_map(
                    query=instance.problem_statement, max_tokens=cfg.context.repo_map_max_tokens,
                )
                if with_repomap else ""
            )
            controller = AgentController(llm, runtime, tools, stream, config=cfg)
            result = controller.run(
                instance.problem_statement, instance.instance_id, run_id=run_id, repo_map=repo_map,
            )
        outcome = asdict(result)
        patch = outcome.pop("patch")
    except Exception as exc:  # noqa: BLE001 - isolate a failed instance from the rest of the batch
        error = f"{type(exc).__name__}: {exc}"
        events = stream.events
        if not events:
            stream.publish(Event(run_id, instance.instance_id, 0, EventType.TASK_STARTED))
        step = events[-1].step if events else 0
        stream.publish(Event(run_id, instance.instance_id, step, EventType.ERROR, {"message": error}))
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
            "errors": [error],
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
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--max-cost", type=float)
    parser.add_argument("--thinking", choices=("", "disabled", "enabled"), help="Override LLM_THINKING")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pipefail", action="store_true")
    parser.add_argument("--with-repomap", action="store_true")
    parser.add_argument("--with-loop-recovery", action="store_true")
    parser.add_argument("--with-verification", action="store_true")
    parser.add_argument("--with-compaction", action="store_true")
    parser.add_argument("--compaction-tokens", type=int)
    args = parser.parse_args()
    cfg = HarnessConfig.from_env()
    if cfg.llm.api_key in {"", "your-api-key-here"}:
        parser.error("Set LLM_API_KEY before running the agent")
    if args.max_steps is not None:
        cfg.max_steps = args.max_steps
    if args.max_cost is not None:
        cfg.max_cost_usd = args.max_cost
    if args.thinking is not None:
        cfg.llm.thinking = args.thinking
    cfg.sandbox.pipefail = args.pipefail or args.with_verification
    cfg.recover_tool_loops = args.with_loop_recovery
    cfg.context.auto_compact = args.with_compaction
    if args.compaction_tokens is not None:
        cfg.context.compaction_trigger_tokens = args.compaction_tokens
    if min(cfg.max_steps, args.workers, cfg.context.compaction_trigger_tokens) < 1 or (
        not math.isfinite(cfg.max_cost_usd) or cfg.max_cost_usd <= 0
    ):
        parser.error("Budgets, worker count and compaction threshold must be positive")

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
    output.mkdir(parents=True, exist_ok=args.resume)
    records = output / "instances"
    records.mkdir(exist_ok=True)
    config = asdict(cfg)
    config["llm"].pop("api_key")
    config.pop("trajectories_dir")
    fingerprint = input_fingerprint([
        [asdict(instance) for instance in instances], config, args.with_repomap, args.with_verification,
    ])
    manifest = output / "inputs.json"
    if args.resume and manifest.is_file():
        if json.loads(manifest.read_text())["fingerprint"] != fingerprint:
            parser.error("--resume requires the same dataset, model, budgets and options")
    elif args.resume:
        # Restore legacy paired exports. A result without a prediction is rerun.
        results_path = output / "results.jsonl"
        predictions_path = output / "predictions.jsonl"
        if results_path.is_file() and predictions_path.is_file():
            predictions = {r["instance_id"]: r for r in read_jsonl(predictions_path, allow_trailing_partial=True)}
            for result in read_jsonl(results_path, allow_trailing_partial=True):
                iid = result["instance_id"]
                if iid not in ids:
                    parser.error("Existing results include an instance outside this dataset")
                if iid in predictions and predictions[iid]["model_name_or_path"] == cfg.llm.model:
                    write_json(records / f"{iid}.json", {"prediction": predictions[iid], "result": result})
    write_json(manifest, {"fingerprint": fingerprint})

    completed = {
        instance.instance_id: json.loads(path.read_text(encoding="utf-8"))
        for instance in instances
        if (path := records / f"{instance.instance_id}.json").is_file()
    }
    pending = [
        item for item in instances
        if completed.get(item.instance_id, {}).get("result", {}).get("status", "error") == "error"
    ]

    def export() -> None:
        ordered = [completed[item.instance_id] for item in instances if item.instance_id in completed]
        for name, field in (("results", "result"), ("predictions", "prediction")):
            content = "".join(json.dumps(record[field], ensure_ascii=False) + "\n" for record in ordered)
            atomic_write(output / f"{name}.jsonl", content)

    llm = OpenAICompatibleClient(cfg.llm)

    def run_and_checkpoint(item: EvalInstance) -> tuple[Prediction, dict]:
        prediction, outcome = run_instance(item, llm, cfg, output, args.with_repomap, args.with_verification)
        write_json(records / f"{item.instance_id}.json", {"prediction": prediction.to_dict(), "result": outcome})
        return prediction, outcome

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_and_checkpoint, item) for item in pending]
        for future in as_completed(futures):
            prediction, outcome = future.result()
            record = {"prediction": prediction.to_dict(), "result": outcome}
            completed[prediction.instance_id] = record
            export()
            print(
                f"{prediction.instance_id}: {outcome['status']}, {outcome['steps']} steps, "
                f"${outcome['total_cost_usd']:.6f}, {outcome['patch_chars']} patch chars",
                flush=True,
            )
    export()
    return int(any(record["result"]["status"] == "error" for record in completed.values()))


if __name__ == "__main__":
    raise SystemExit(main())
