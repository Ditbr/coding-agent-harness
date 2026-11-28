"""SWE-bench JSONL I/O and ablation summary helpers."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from harness.eval.models import (
    AgentTask,
    EvalInstance,
    EvalResult,
    FailureCategory,
    Prediction,
    RunSummary,
)

NETWORK_FAILURES = re.compile(
    r"CERTIFICATE_VERIFY_FAILED|429 Client Error|Response \[429\]|"
    r"Temporary failure in name resolution|Name or service not known|Network is unreachable|"
    r"Failed to establish a new connection|ConnectTimeout|ReadTimeout|"
    r"""HTTPS?ConnectionPool\(host=['"]httpbin\.org['"], port=\d+\): Max retries exceeded""",
    re.IGNORECASE,
)


def network_failure_evidence(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return sorted(set(NETWORK_FAILURES.findall(path.read_text(encoding="utf-8", errors="replace"))))


def read_jsonl(path: Path, *, allow_trailing_partial: bool = False) -> list[dict]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    if allow_trailing_partial and not line.endswith("\n"):
                        break
                    raise ValueError(f"{path}:{line_number}: {exc.msg}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: expected a JSON object")
                rows.append(row)
    return rows


def load_instances_jsonl(path: Path) -> list[EvalInstance]:
    def test_ids(raw: dict, name: str) -> list[str]:
        value = raw.get(name, raw.get(name.lower(), []))
        return json.loads(value) if isinstance(value, str) else list(value)

    return [
        EvalInstance(
            instance_id=raw["instance_id"],
            repo=raw.get("repo", ""),
            base_commit=raw.get("base_commit", ""),
            problem_statement=raw["problem_statement"],
            docker_image=raw.get("image") or raw.get("docker_image", ""),
            fail_to_pass=test_ids(raw, "FAIL_TO_PASS"),
            pass_to_pass=test_ids(raw, "PASS_TO_PASS"),
            test_modules=list(dict.fromkeys(
                line.removeprefix("+++ b/").split("\t", 1)[0]
                for line in raw.get("test_patch", "").splitlines()
                if line.startswith("+++ b/") and line.split("\t", 1)[0].endswith(".py")
            )),
        )
        for raw in read_jsonl(path)
    ]


def load_agent_tasks_jsonl(path: Path) -> list[AgentTask]:
    """Project a dataset onto the fields available to the agent at inference time."""
    return [
        AgentTask(
            instance_id=row["instance_id"],
            repo=row.get("repo", ""),
            base_commit=row.get("base_commit", ""),
            problem_statement=row["problem_statement"],
            docker_image=row.get("image") or row.get("docker_image", ""),
        )
        for row in read_jsonl(path)
    ]


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
