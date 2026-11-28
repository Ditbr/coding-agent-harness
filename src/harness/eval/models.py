"""Evaluation data models and standardized Failure Taxonomy (E1~E6)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FailureCategory(str, Enum):
    NONE = "NONE"
    E1_LOC_MISS = "E1_LOC_MISS"          # Wrong file / function localization
    E2_EDIT_FAIL = "E2_EDIT_FAIL"        # Edit match failure or syntax error
    E3_CTX_BLOAT = "E3_CTX_BLOAT"        # Context overflow / forgetting goal
    E4_NO_VERIFY = "E4_NO_VERIFY"        # Submitted without reproducing/testing
    E5_REGRESSION = "E5_REGRESSION"      # F2P passed, P2P regressed
    E6_LOOP_STUCK = "E6_LOOP_STUCK"      # Repeated loop / max steps / timeout


@dataclass(slots=True)
class EvalInstance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    docker_image: str = ""
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    test_modules: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Prediction:
    """SWE-bench harness compatible prediction entry."""
    instance_id: str
    model_name_or_path: str
    model_patch: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvalResult:
    instance_id: str
    resolved: bool
    steps: int
    cost_usd: float
    prompt_tokens: int = 0
    cached_tokens: int = 0
    failure_category: FailureCategory = FailureCategory.NONE
    notes: str = ""


@dataclass(slots=True)
class RunSummary:
    run_id: str
    total: int
    resolved: int
    pass_at_1: float
    avg_steps: float
    avg_cost_usd: float
    cache_hit_rate: float
    failure_breakdown: dict[str, int] = field(default_factory=dict)

    def to_markdown_row(self) -> str:
        return (
            f"| {self.run_id} | {self.resolved}/{self.total} ({self.pass_at_1:.1%}) "
            f"| {self.avg_steps:.1f} | ${self.avg_cost_usd:.4f} | {self.cache_hit_rate:.1%} |"
        )
