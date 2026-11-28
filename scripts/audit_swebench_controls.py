"""Compare Gold and Empty controls with and without container networking."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from harness.eval.artifacts import write_json
from harness.eval.runner import network_failure_evidence, read_jsonl


def observed_empty_failures(row: dict, logfile: Path) -> list[str]:
    observed = list(row.get("observed_f2p_failures") or [])
    if not row["instance_id"].startswith("django__django-") or not logfile.is_file():
        return observed
    # Django's unittest report names a failing subtest after the parent test ID.
    # SWE-bench can omit that parent from observed_f2p_failures.
    log = logfile.read_text(encoding="utf-8", errors="replace")
    for test in (row.get("fail_to_pass") or {}).get("failure", ()):
        header = rf"^(?:FAIL|ERROR): {re.escape(test)}(?=\s|$)"
        if test not in observed and re.search(header, log, re.MULTILINE):
            observed.append(test)
    return observed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    for profile in ("default", "offline"):
        for mode in ("gold", "empty"):
            parser.add_argument(f"--{profile}-{mode}", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = read_jsonl(args.dataset)
    requests_ids = {row["instance_id"] for row in rows if row["repo"] == "psf/requests"}
    all_ids = {row["instance_id"] for row in rows}
    conditions = {}
    for profile, network, expected in (("default", "default", all_ids), ("offline", "none", requests_ids)):
        for mode in ("gold", "empty"):
            path = getattr(args, f"{profile}_{mode}")
            report = json.loads(path.read_text(encoding="utf-8"))
            records = {row["instance_id"]: row for row in report["instances"]}
            if report["mode"] != mode or report["network"] != network or records.keys() != expected:
                parser.error(f"{path} does not match the expected {profile} {mode} controls")
            for row in records.values():
                if row.get("log_dir"):
                    logfile = path.parent / row["log_dir"] / "test_output.txt"
                    evidence = set(row.get("network_failure_evidence", ())) | set(network_failure_evidence(logfile))
                    if evidence:
                        row["network_failure_evidence"] = sorted(evidence)
                    if mode == "empty":
                        row["observed_f2p_failures"] = observed_empty_failures(row, logfile)
            conditions[f"{profile}_{mode}"] = records

    audit = []
    for row in rows:
        iid = row["instance_id"]
        outcomes = {key: value[iid] for key, value in conditions.items() if iid in value}
        gold, empty = (outcomes[f"default_{kind}"] for kind in ("gold", "empty"))
        gold_ok = gold["status"] == "resolved"
        empty_ok = (
            empty["status"] == "unresolved" and bool(empty.get("observed_f2p_failures"))
            and not (empty.get("pass_to_pass") or {}).get("failure")
        )
        network_evidence = {
            key: value["network_failure_evidence"] for key, value in outcomes.items()
            if value.get("network_failure_evidence") and (
                (key.endswith("_gold") and not value["resolved"])
                or (key.endswith("_empty") and (
                    not value.get("observed_f2p_failures")
                    or (value.get("pass_to_pass") or {}).get("failure")
                ))
            )
        }
        interrupted = any(value["status"] in {"timeout", "evaluation_error"} for value in outcomes.values())
        audit.append({
            "instance_id": iid,
            "default_controls_ok": gold_ok and empty_ok,
            "observed_external_noise": bool(network_evidence),
            "network_failure_evidence": network_evidence,
            "has_infrastructure_error": interrupted,
            "conditions": {
                key: {field: value.get(field) for field in
                      ("status", "observed_f2p_failures", "log_dir", "detail", "seconds")}
                for key, value in outcomes.items()
            },
        })
    write_json(args.output, {
        "total": len(audit),
        "default_controls_ok": sum(row["default_controls_ok"] for row in audit),
        "external_noise_ids": [row["instance_id"] for row in audit if row["observed_external_noise"]],
        "infra_error_ids": [row["instance_id"] for row in audit if row["has_infrastructure_error"]],
        "reports": {key: str(getattr(args, key)) for key in conditions},
        "instances": audit,
    })


if __name__ == "__main__":
    main()
