"""SWE-bench JSONL I/O and ablation summary helpers."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from harness.eval.models import EvalInstance, EvalResult, FailureCategory, Prediction, RunSummary


def load_instances_jsonl(path: Path) -> list[EvalInstance]:
    instances: list[EvalInstance] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            instances.append(EvalInstance(
                instance_id=raw["instance_id"],
                repo=raw.get("repo", ""),
                base_commit=raw.get("base_commit", ""),
                problem_statement=raw["problem_statement"],
                docker_image=raw.get("docker_image", ""),
                fail_to_pass=list(raw.get("FAIL_TO_PASS", raw.get("fail_to_pass", []))),
                pass_to_pass=list(raw.get("PASS_TO_PASS", raw.get("pass_to_pass", []))),
            ))
    return instances


def write_predictions_jsonl(predictions: list[Prediction], output_path: Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for pred in predictions:
            fh.write(json.dumps(pred.to_dict(), ensure_ascii=False) + "\n")
    return out


def summarize_results(run_id: str, results: list[EvalResult]) -> RunSummary:
    total = len(results)
    if total == 0:
        return RunSummary(run_id=run_id, total=0, resolved=0, pass_at_1=0.0, avg_steps=0.0, avg_cost_usd=0.0, cache_hit_rate=0.0)

    resolved = sum(1 for r in results if r.resolved)
    avg_steps = sum(r.steps for r in results) / total
    avg_cost = sum(r.cost_usd for r in results) / total
    total_prompt = sum(r.prompt_tokens for r in results)
    total_cached = sum(r.cached_tokens for r in results)
    cache_hit = (total_cached / total_prompt) if total_prompt > 0 else 0.0
    failures = Counter(
        r.failure_category.value
        for r in results
        if not r.resolved and r.failure_category != FailureCategory.NONE
    )
    return RunSummary(
        run_id=run_id,
        total=total,
        resolved=resolved,
        pass_at_1=resolved / total,
        avg_steps=avg_steps,
        avg_cost_usd=avg_cost,
        cache_hit_rate=cache_hit,
        failure_breakdown=dict(failures),
    )
