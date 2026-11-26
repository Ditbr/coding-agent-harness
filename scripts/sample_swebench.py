"""Generate the frozen Week 1 subsets from a pinned SWE-bench Verified revision."""

from __future__ import annotations

import argparse
import json
import random
import tempfile
import urllib.request
from collections import Counter
from pathlib import Path

DATASET = "SWE-bench/SWE-bench_Verified"
REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"
SEED = 20261126
REPOS = (
    "django/django",
    "matplotlib/matplotlib",
    "psf/requests",
    "pytest-dev/pytest",
    "scikit-learn/scikit-learn",
    "sympy/sympy",
)
DIFFICULTIES = (
    "<15 min fix", "15 min - 1 hour", "1-4 hours", "<15 min fix", "15 min - 1 hour",
)
ROOT = Path(__file__).resolve().parents[1]


def sample(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    selected = []
    smoke = []
    for repo in REPOS:
        pool = sorted(
            (row for row in rows if row["repo"] == repo),
            key=lambda row: row["instance_id"],
        )
        rng.shuffle(pool)
        env_counts = Counter((row["version"], row["environment_setup_commit"]) for row in pool)
        used_envs: Counter = Counter()
        chosen = []
        for difficulty in DIFFICULTIES:
            candidates = [row for row in pool if row["difficulty"] == difficulty] or pool
            row = max(
                candidates,
                key=lambda row: (
                    used_envs[row["version"], row["environment_setup_commit"]],
                    env_counts[row["version"], row["environment_setup_commit"]],
                ),
            )
            used_envs[row["version"], row["environment_setup_commit"]] += 1
            pool.remove(row)
            chosen.append(row)
        selected.extend(chosen)
        if repo != "matplotlib/matplotlib":
            smoke.append(min(chosen, key=lambda row: (
                row["difficulty"] != DIFFICULTIES[0],
                len(row["PASS_TO_PASS"]) + len(row["FAIL_TO_PASS"]),
            )))
    return selected, smoke


def main() -> None:
    from pyarrow.parquet import read_table

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, help="Local copy of the pinned source Parquet")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        source = args.parquet
        if source is None:
            source = Path(tmp) / "verified.parquet"
            urllib.request.urlretrieve(
                f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}"
                "/data/test-00000-of-00001.parquet",
                source,
            )
        rows = read_table(source).to_pylist()
    if len(rows) != 500 or len({row["instance_id"] for row in rows}) != 500:
        parser.error("Expected 500 distinct SWE-bench Verified instances")
    baseline, smoke = sample(rows)
    outputs = {
        args.output_dir / name: "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in subset
        )
        for name, subset in (("swebench_verified_30.jsonl", baseline), ("smoke_5.jsonl", smoke))
    }
    for path, content in outputs.items():
        if path.exists() and path.read_text(encoding="utf-8") != content:
            parser.error(f"{path} is frozen and differs from this sample")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path, content in outputs.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
