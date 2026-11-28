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

from harness.eval.artifacts import input_fingerprint, write_json
from harness.eval.models import Prediction
from harness.eval.runner import network_failure_evidence, read_jsonl, write_predictions_jsonl
from harness.runtime.docker_env import docker_environment

ROOT = Path(__file__).resolve().parents[1]

RETRYABLE_STATUSES = {"evaluation_error", "timeout"}
TRANSPORT_ERRORS = (
    "connection reset", "connection refused", "connection aborted", "remote end closed",
    "read timed out", "connect timeout", "broken pipe", "server disconnected", "unexpected eof",
)


def evaluate(args: argparse.Namespace, rows: list[dict], predictions: dict[str, dict]) -> dict:
    import docker
    from requests.exceptions import ConnectionError, RequestException, Timeout
    from swebench.harness.constants import (
        LOG_INSTANCE,
        LOG_REPORT,
        LOG_TEST_OUTPUT,
        RUN_EVALUATION_LOG_DIR,
        TestStatus,
    )
    from swebench.harness.grading import get_logs_eval
    from swebench.harness.run_evaluation import run_instance
    from swebench.harness.utils import make_test_spec

    docker_env = docker_environment()
    if not docker_env.get("DOCKER_HOST") or docker_env.get("DOCKER_CONTEXT"):
        docker_env["DOCKER_HOST"] = subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
            env=docker_env, text=True,
        ).strip()
    # Requests reads proxy exclusion from the process environment.
    for key in ("NO_PROXY", "no_proxy"):
        os.environ[key] = docker_env[key]

    start = time.monotonic()
    run_id = f"{args.mode}-{uuid.uuid4().hex[:12]}"
    records = Path("instances")
    records.mkdir(exist_ok=True)
    pip_no_build_isolation = getattr(args, "pip_no_build_isolation", True)

    def _wrap_container_create(orig_create):
        def _wrapped_create(*c_args, **c_kwargs):
            if args.network == "none":
                c_kwargs.setdefault("network_mode", "none")
            if pip_no_build_isolation:
                extra_env = {
                    "PIP_NO_BUILD_ISOLATION": "1",
                    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                }
                existing = c_kwargs.get("environment")
                if isinstance(existing, dict):
                    c_kwargs["environment"] = {**extra_env, **existing}
                elif isinstance(existing, list):
                    merged = list(existing)
                    existing_keys = {entry.split("=", 1)[0] for entry in merged if "=" in entry}
                    for k, v in extra_env.items():
                        if k not in existing_keys:
                            merged.append(f"{k}={v}")
                    c_kwargs["environment"] = merged
                else:
                    c_kwargs["environment"] = extra_env
            return orig_create(*c_args, **c_kwargs)

        return _wrapped_create

    def evaluate_one(row: dict) -> dict:
        spec = make_test_spec(row)
        iid = spec.instance_id
        prediction = predictions.get(iid)
        result = {
            "instance_id": iid,
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

        task_start = time.monotonic()
        model = prediction["model_name_or_path"].replace("/", "__")
        result["status"] = "evaluation_error"
        for attempt in range(args.retries + 1):
            attempt_id = run_id if attempt == 0 else f"{run_id}-r{attempt}"
            log_dir = RUN_EVALUATION_LOG_DIR / attempt_id / model / iid
            result.update(log_dir=str(log_dir), attempts=attempt + 1)
            client = None
            official = None
            failure = ""
            transient = False
            try:
                client = docker.from_env(
                    environment=docker_env, timeout=args.docker_timeout,
                    use_ssh_client=docker_env["DOCKER_HOST"].startswith("ssh://"),
                )
                if args.network == "none" or pip_no_build_isolation:
                    client.containers.create = _wrap_container_create(client.containers.create)
                try:
                    client.images.get(spec.image)
                except docker.errors.ImageNotFound:
                    client.images.pull(spec.image, platform="linux/amd64")
                official = run_instance(
                    spec, prediction, client, attempt_id,
                    timeout=args.timeout, skip_patch=args.mode == "empty",
                )
            except (docker.errors.DockerException, RequestException) as exc:
                failure = str(exc)
                transient = isinstance(exc, (ConnectionError, Timeout))
                transient |= getattr(exc, "status_code", None) in {502, 503, 504}
            finally:
                if client is not None:
                    client.close()

            # A dropped connection during container cleanup can leave a complete official report.
            report_path = log_dir / LOG_REPORT
            if official is None and report_path.is_file():
                try:
                    official = (iid, json.loads(report_path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    pass
            log_path = log_dir / LOG_INSTANCE
            log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            if official is not None:
                report = official[1][iid]
                tests = report.get("tests_status")
                if not tests or report.get("infra_failure"):
                    result["detail"] = report.get("infra_failure_reason", "No gradeable test output")
                else:
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
                break
            if "Test timed out after" in log:
                result["status"] = "timeout"
                break
            if "Failed to apply patch to container" in log:
                result["status"] = "patch_apply_failed"
                break
            transient |= any(marker in (failure + log).lower() for marker in TRANSPORT_ERRORS)
            if not transient or attempt == args.retries:
                result["detail"] = failure or "Official harness did not return a report"
                break
            time.sleep(2 ** attempt)

        test_log = Path(result["log_dir"]) / LOG_TEST_OUTPUT
        if matches := network_failure_evidence(test_log):
            result["network_failure_evidence"] = matches
        result["seconds"] = round(time.monotonic() - task_start, 3)
        return result

    def run_or_resume(row: dict) -> dict:
        path = records / f'{row["instance_id"]}.json'
        if args.resume and path.is_file():
            prior = json.loads(path.read_text(encoding="utf-8"))
            if prior["status"] not in RETRYABLE_STATUSES:
                return prior
        result = evaluate_one(row)
        write_json(path, result)
        return result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_or_resume, rows))

    resolved = sum(result["resolved"] for result in results)
    summary = {
        "mode": args.mode,
        "network": args.network,
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
    parser.add_argument("--docker-timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--network", choices=("default", "none"), default="default")
    parser.add_argument(
        "--pip-no-build-isolation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Inject PIP_NO_BUILD_ISOLATION=1 in eval containers to prevent matplotlib pip build hangs",
    )
    parser.add_argument("--noise-audit", type=Path)
    args = parser.parse_args()
    if min(args.workers, args.timeout, args.docker_timeout) < 1 or args.retries < 0:
        parser.error("Workers and timeouts must be positive, retries nonnegative")
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
    excluded: set[str] = set()
    if args.noise_audit:
        noise = json.loads(args.noise_audit.read_text(encoding="utf-8"))
        audited = {row["instance_id"] for row in noise["instances"]}
        if not ids <= audited:
            parser.error("--noise-audit does not cover every instance in the dataset")
        excluded = set(noise["external_noise_ids"]) & ids
    fingerprint = input_fingerprint([args.mode, args.network, rows, predictions])
    args.output_dir.mkdir(parents=True, exist_ok=args.resume)
    os.chdir(args.output_dir)
    manifest = Path("inputs.json")
    if args.resume:
        if not manifest.is_file() or json.loads(manifest.read_text())["fingerprint"] != fingerprint:
            parser.error("--resume requires the same dataset, predictions, mode and network")
    else:
        write_json(manifest, {"fingerprint": fingerprint})
    if args.mode != "predictions":
        write_predictions_jsonl(control, Path("predictions.jsonl"))
    summary = evaluate(args, rows, predictions)
    if args.noise_audit:
        remaining = [r for r in summary["instances"] if r["instance_id"] not in excluded]
        resolved = sum(r["resolved"] for r in remaining)
        summary["without_external_noise"] = {
            "excluded_ids": sorted(excluded), "total": len(remaining), "resolved": resolved,
            "pass_at_1": resolved / len(remaining) if remaining else None,
        }
    write_json(Path("summary.json"), summary)
    print(f"{args.mode}: {summary['resolved']}/{summary['total']} ({summary['pass_at_1']:.1%})")
    if not summary.get("sanity_passed", True):
        return 1
    return int(any(r["status"] in {"evaluation_error", "timeout"} for r in summary["instances"]))


if __name__ == "__main__":
    raise SystemExit(main())
