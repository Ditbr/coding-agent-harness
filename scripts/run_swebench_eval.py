"""Evaluate frozen SWE-bench tasks and report per-instance FAIL_TO_PASS and PASS_TO_PASS."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness.eval.models import Prediction
from harness.eval.runner import read_jsonl, write_predictions_jsonl

ROOT = Path(__file__).resolve().parents[1]

def evaluate(args: argparse.Namespace, rows: list[dict], predictions: dict[str, dict]) -> dict:
    import docker
    from swebench.harness.constants import (
        LOG_INSTANCE,
        LOG_TEST_OUTPUT,
        RUN_EVALUATION_LOG_DIR,
        TestStatus,
    )
    from swebench.harness.grading import get_logs_eval
    from swebench.harness.run_evaluation import run_instance
    from swebench.harness.utils import make_test_spec

    # The Python Docker SDK does not automatically follow Docker CLI contexts.
    docker_env = os.environ.copy()
    if not docker_env.get("DOCKER_HOST") or docker_env.get("DOCKER_CONTEXT"):
        docker_env["DOCKER_HOST"] = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            text=True,
        ).strip()
    client = docker.from_env(environment=docker_env, timeout=1800)
    start = time.monotonic()
    run_id = f"{args.mode}-{uuid.uuid4().hex[:12]}"

    def evaluate_one(row: dict) -> dict:
        task_start = time.monotonic()
        spec = make_test_spec(row)
        instance_id = spec.instance_id
        prediction = predictions.get(instance_id)
        result = {
            "instance_id": instance_id,
            "status": "missing_prediction",
            "resolved": False,
            "fail_to_pass": None,
            "pass_to_pass": None,
            "seconds": 0.0,
        }
        if prediction is None:
            return result
        if args.mode == "predictions" and not prediction["model_patch"].strip():
            return {**result, "status": "empty_patch"}

        model = prediction["model_name_or_path"].replace("/", "__")
        log_dir = RUN_EVALUATION_LOG_DIR / run_id / model / instance_id
        try:
            try:
                client.images.get(spec.image)
            except docker.errors.ImageNotFound:
                client.images.pull(spec.image, platform="linux/amd64")
        except docker.errors.DockerException as exc:
            return {
                **result, "status": "evaluation_error", "detail": str(exc),
                "seconds": round(time.monotonic() - task_start, 3),
            }
        official = run_instance(
            spec, prediction, client, run_id,
            timeout=args.timeout, skip_patch=args.mode == "empty",
        )
        result.update(
            status="evaluation_error", log_dir=str(log_dir),
            seconds=round(time.monotonic() - task_start, 3),
        )
        if official is None:
            log_path = log_dir / LOG_INSTANCE
            if log_path.is_file():
                log = log_path.read_text(encoding="utf-8", errors="replace")
                if "Test timed out after" in log:
                    result["status"] = "timeout"
                elif "Failed to apply patch to container" in log:
                    result["status"] = "patch_apply_failed"
            return result

        report = official[1][instance_id]
        tests = report.get("tests_status")
        if not tests or report.get("infra_failure"):
            result["detail"] = report.get("infra_failure_reason", "No gradeable test output")
            return result
        result.update(
            status="resolved" if report["resolved"] else "unresolved",
            resolved=report["resolved"],
            fail_to_pass=tests["FAIL_TO_PASS"],
            pass_to_pass=tests["PASS_TO_PASS"],
        )
        if args.mode == "empty":
            statuses, _ = get_logs_eval(spec, log_dir / LOG_TEST_OUTPUT)
            result["observed_f2p_failures"] = [
                test for test in spec.FAIL_TO_PASS
                if statuses.get(test) in {TestStatus.FAILED.value, TestStatus.ERROR.value}
            ]
        return result

    try:
        client.ping()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(evaluate_one, rows))
    finally:
        client.close()

    resolved = sum(result["resolved"] for result in results)
    summary = {
        "mode": args.mode,
        "run_id": run_id,
        "total": len(results),
        "resolved": resolved,
        "pass_at_1": resolved / len(results),
        "seconds": round(time.monotonic() - start, 3),
        "instances": results,
    }
    if args.mode == "empty":
        summary["sanity_passed"] = all(
            r["status"] == "unresolved" and r["observed_f2p_failures"] for r in results
        )
    elif args.mode == "gold":
        summary["sanity_passed"] = resolved == len(results)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/smoke_5.jsonl")
    parser.add_argument("--mode", choices=("empty", "gold", "predictions"), required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for logs and report")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.workers < 1 or args.timeout < 1:
        parser.error("--workers and --timeout must be positive")
    if (args.mode == "predictions") != bool(args.predictions):
        parser.error("--predictions is required only in predictions mode")
    rows = read_jsonl(args.dataset)
    ids = {row["instance_id"] for row in rows}
    if not ids or len(ids) != len(rows):
        parser.error("Dataset must contain unique instance IDs")
    if args.predictions:
        supplied = read_jsonl(args.predictions)
        predictions = {row["instance_id"]: row for row in supplied}
        if len(predictions) != len(supplied) or set(predictions) - ids:
            parser.error("Predictions contain duplicate or unknown instance IDs")
        for row in supplied:
            model = row.get("model_name_or_path")
            if (not isinstance(model, str) or not re.fullmatch(r"[\w./-]+", model)
                    or model in {".", ".."} or not isinstance(row.get("model_patch"), str)):
                parser.error(f"Invalid prediction for {row['instance_id']}")
    else:
        control = [
            Prediction(row["instance_id"], args.mode, row["patch"] if args.mode == "gold" else "")
            for row in rows
        ]
        predictions = {p.instance_id: p.to_dict() for p in control}

    for instance_id in ids:
        if not re.fullmatch(r"[\w.-]+", instance_id) or instance_id in {".", ".."}:
            parser.error(f"Invalid instance ID {instance_id!r}")
    args.output_dir.mkdir(parents=True)
    os.chdir(args.output_dir)
    if args.mode != "predictions":
        write_predictions_jsonl(control, Path("predictions.jsonl"))
    summary = evaluate(args, rows, predictions)
    Path("summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"{args.mode}: {summary['resolved']}/{summary['total']} ({summary['pass_at_1']:.1%})")
    if not summary.get("sanity_passed", True):
        return 1
    return int(any(r["status"] in {"evaluation_error", "timeout"} for r in summary["instances"]))


if __name__ == "__main__":
    raise SystemExit(main())
