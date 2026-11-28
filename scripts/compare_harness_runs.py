"""Summarize matched runs for the RepoMap, guardrail, and compaction ablations."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import mean, median

from harness.eval.artifacts import write_json
from harness.eval.runner import read_jsonl

TEST_RUNNER = re.compile(r"\bpytest\b|\bunittest\b|tests/runtests\.py|\bbin/test\b")
PASS_OUTPUT = re.compile(r"\b[1-9]\d* passed\b|^OK$", re.MULTILINE)
FAIL_OUTPUT = re.compile(r"\b[1-9]\d* (?:failed|errors?)\b|^FAILED", re.MULTILINE)


def analyze(
    directory: Path,
    report: Path,
    rows: list[dict],
    *,
    pricing: tuple[float, float, float, str] | None = None,
) -> dict:
    scored = {row["instance_id"]: row for row in json.loads(report.read_text())["instances"]}
    results = {row["instance_id"]: row for row in read_jsonl(directory / "results.jsonl")}
    ids = {row["instance_id"] for row in rows}
    if results.keys() != ids or scored.keys() != ids:
        raise ValueError(f"{directory} and {report} must cover the full comparison dataset")
    instances = []
    for row in rows:
        iid = row["instance_id"]
        result, score = results[iid], scored[iid]
        events = read_jsonl(directory / result["trajectory"])
        paths = set(re.findall(r"^\+\+\+ b/(.+)$", row["patch"], re.MULTILINE))
        paths.update(re.findall(r"^--- a/(.+)$", row["patch"], re.MULTILINE))
        location_step = min(
            (event["step"] for event in events if event["event_type"] == "action"
             and event["payload"]["tool"] in {"view_file", "edit_file"}
             and event["payload"]["args"].get("path", "").removeprefix("./") in paths),
            default=None,
        )
        actions = {
            event["payload"]["call_id"]: event["payload"]
            for event in events if event["event_type"] == "action"
        }
        last_edit = -1
        last_passing_test = -1
        for position, event in enumerate(events):
            if event["event_type"] != "observation":
                continue
            observation = event["payload"]
            if observation["tool"] in {"edit_file", "rollback"} and observation["status"] == "ok":
                last_edit = position
            if observation.get("exit_code") != 0:
                continue
            action = actions.get(observation.get("call_id"), {})
            command = action.get("args", {}).get("command", "")
            output = observation.get("content", "")
            metadata = observation.get("metadata", {})
            verdict = metadata.get("test_result")
            passed = verdict == "passed" if verdict is not None else (
                metadata.get("test") or (
                    TEST_RUNNER.search(command) and PASS_OUTPUT.search(output) and not FAIL_OUTPUT.search(output)
                )
            )
            if passed:
                last_passing_test = position
        instances.append({
            "instance_id": iid,
            "resolved": score["resolved"],
            "score_status": score["status"],
            "agent_status": result["status"],
            "first_gold_file_tool_step": location_step,
            "empty_patch": result.get("patch_chars") == 0,
            "loop_detected": result["status"] == "loop_detected",
            "has_passing_test_after_last_observed_edit": last_passing_test > last_edit,
            "compactions": sum(event["event_type"] == "compaction" for event in events),
        })
    count = len(instances)
    found = [r["first_gold_file_tool_step"] for r in instances if r["first_gold_file_tool_step"] is not None]
    prompt = sum(r["total_prompt_tokens"] for r in results.values())
    cached = sum(r["total_cached_tokens"] for r in results.values())
    completion = sum(r["total_completion_tokens"] for r in results.values())
    resolved = sum(r["resolved"] for r in instances)
    summary = {
        "total": count,
        "resolved": resolved,
        "pass_at_1": resolved / count,
        "average_cost_usd": mean(r["total_cost_usd"] for r in results.values()),
        "total_cost_usd": sum(r["total_cost_usd"] for r in results.values()),
        "total_prompt_tokens": prompt,
        "total_completion_tokens": completion,
        "total_cached_tokens": cached,
        "cache_hit_rate": cached / prompt if prompt else None,
        "gold_file_located": len(found),
        "mean_first_gold_file_tool_step": mean(found) if found else None,
        "median_first_gold_file_tool_step": median(found) if found else None,
        "empty_patches": sum(r["empty_patch"] for r in instances),
        "loops_detected": sum(r["loop_detected"] for r in instances),
        "unresolved_empty_or_loop": sum(
            not r["resolved"] and (r["empty_patch"] or r["loop_detected"]) for r in instances
        ),
        "unresolved_without_passing_test_after_last_observed_edit": sum(
            not r["resolved"] and not r["has_passing_test_after_last_observed_edit"]
            for r in instances
        ),
        "compactions": sum(r["compactions"] for r in instances),
        "instances": instances,
    }
    if pricing is not None:
        in_p, cache_p, out_p, currency = pricing
        uncached = max(0, prompt - cached)
        est_total = (uncached / 1_000_000) * in_p + (cached / 1_000_000) * cache_p + (completion / 1_000_000) * out_p
        summary["pricing"] = {
            "currency": currency,
            "input_per_1m": in_p,
            "cached_input_per_1m": cache_p,
            "output_per_1m": out_p,
            "total_cost": round(est_total, 4),
            "cost_per_task": round(est_total / count, 4),
            "cost_per_resolved": round(est_total / resolved, 4) if resolved else None,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, nargs=2, required=True, metavar=("RUN", "SCORE"))
    parser.add_argument(
        "--variant", type=Path, nargs=2, action="append", required=True, metavar=("RUN", "SCORE"),
        help="Variant run and score report. Repeat to compare several variants.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-price", type=float, help="Uncached input price per 1M tokens")
    parser.add_argument("--cached-price", type=float, help="Cached input price per 1M tokens")
    parser.add_argument("--output-price", type=float, help="Output price per 1M tokens")
    parser.add_argument("--currency", type=str, default="CNY", help="Currency label for custom pricing (default: CNY)")
    args = parser.parse_args()
    rows = read_jsonl(args.dataset)
    if not rows:
        parser.error("The comparison dataset is empty")
    price_args = (args.input_price, args.cached_price, args.output_price)
    if any(p is not None for p in price_args) and not all(p is not None for p in price_args):
        parser.error("Provide --input-price, --cached-price, and --output-price together")
    pricing = (*price_args, args.currency) if all(p is not None for p in price_args) else None
    variant_names = [directory.name for directory, _ in args.variant]
    if len(set(variant_names)) != len(variant_names):
        parser.error("Variant run directories must have distinct names")
    comparison = {"baseline": analyze(*args.baseline, rows, pricing=pricing)}
    variants = {directory.name: analyze(directory, report, rows, pricing=pricing) for directory, report in args.variant}
    if len(variants) == 1:
        comparison["variant"] = next(iter(variants.values()))
    else:
        comparison["variants"] = variants
    write_json(args.output, comparison)


if __name__ == "__main__":
    main()
