"""Regressions for Docker transport, batch resume, and opt-in agent features."""

import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

try:
    import pytest
except ModuleNotFoundError as exc:
    from unittest import SkipTest

    raise SkipTest("Fix regressions require pytest") from exc

from harness.agent.controller import AgentController
from harness.config import ContextConfig, HarnessConfig
from harness.eval.models import Prediction
from harness.events.schema import EventType, ToolCallRequest
from harness.llm.client import LLMResponse, MockLLMClient
from harness.repomap.mapper import RepoMapper
from harness.runtime.base import CommandResult
from harness.runtime.docker import DockerSandboxRuntime
from harness.runtime.docker_env import docker_environment
from harness.runtime.local import LocalWorkspaceRuntime
from harness.tools.aci import build_default_tool_registry
from harness.tools.verification import VerificationGate


def load_script(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py",
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_audit_recovers_django_empty_subtest_failures_from_log(tmp_path):
    script = load_script("audit_swebench_controls")
    case = "test_invalid (forms_tests.ValidatorTests)"
    missing = "test_missing (forms_tests.ValidatorTests)"
    logfile = tmp_path / "test_output.txt"
    logfile.write_text(f"FAIL: {case} [EmailValidator] (value='a')\n", encoding="utf-8")
    result = {
        "instance_id": "django__django-13212",
        "observed_f2p_failures": [],
        "fail_to_pass": {"failure": [case, missing]},
    }
    assert script.observed_empty_failures(result, logfile) == [case]


def test_docker_proxy_and_pipefail(monkeypatch, tmp_path):
    merger = docker_environment({"NO_PROXY": "one.test,localhost", "no_proxy": "two.test"})
    assert merger["NO_PROXY"] == merger["no_proxy"] == "127.0.0.1,localhost,::1,one.test,two.test"
    assert LocalWorkspaceRuntime(tmp_path).run_command("false | true").exit_code != 0
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:1234")
    runner = Mock(side_effect=[
        SimpleNamespace(returncode=0, stdout="id", stderr=""),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(returncode=1, stdout="", stderr=""),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
    ])
    monkeypatch.setattr("harness.runtime.docker.subprocess.run", runner)
    with DockerSandboxRuntime() as runtime:
        assert runtime.run_command("false | true").exit_code != 0
    assert all(
        "127.0.0.1" in call.kwargs["env"]["NO_PROXY"]
        and call.kwargs["env"]["HTTP_PROXY"] == os.environ["HTTP_PROXY"]
        for call in runner.call_args_list
    )
    assert "bash -o pipefail" in " ".join(runner.call_args_list[2].args[0])


@pytest.mark.parametrize("export_timeout", [False, True])
def test_docker_host_exec_timeout_preserves_patch(monkeypatch, export_timeout):
    patch = "diff --git a/file.py b/file.py\n--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n"
    actions = [
        subprocess.CompletedProcess([], 0, stdout="container", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        subprocess.TimeoutExpired("docker exec", 11, output=b"partial\n", stderr=b"cli stalled\n"),
    ]
    if export_timeout:
        actions.append(subprocess.TimeoutExpired("docker exec", 40, output=b"partial diff"))
    actions.extend([
        subprocess.CompletedProcess([], 0, stdout=patch, stderr=""),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    ])
    runner = Mock(side_effect=actions)
    monkeypatch.setattr("harness.runtime.docker.subprocess.run", runner)

    with DockerSandboxRuntime() as runtime:
        result = runtime.run_command("git status; git diff", timeout=1)
        assert result.timed_out and result.exit_code == 124
        assert result.stdout == "partial\n"
        assert "cli stalled" in result.stderr
        assert runtime.git_diff() == patch
        calls = [call.args[0] for call in runner.call_args_list]
        assert all(args[1] == "exec" and args[4] == "container" for args in calls[1:])
        assert sum("git diff --cached" in args[-1] for args in calls) == 1 + export_timeout

    assert runner.call_args.args[0] == ["docker", "rm", "-f", "container"]


def test_evaluation_retries_requests_errors_and_writes_all_rows(monkeypatch, tmp_path):
    docker = pytest.importorskip("docker")
    pytest.importorskip("swebench")
    from requests.exceptions import ConnectionError

    script = load_script("run_swebench_eval")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:12345")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(script.time, "sleep", lambda _: None)
    client = Mock()
    client.images.get.side_effect = [ConnectionError("connection reset"), None]
    monkeypatch.setattr(docker, "from_env", Mock(return_value=client))
    monkeypatch.setattr(
        "swebench.harness.utils.make_test_spec",
        lambda row: SimpleNamespace(instance_id=row["instance_id"], image="image"),
    )
    def grade(spec, *args, **kwargs):
        return spec.instance_id, {spec.instance_id: {
            "resolved": True, "tests_status": {"FAIL_TO_PASS": {}, "PASS_TO_PASS": {}},
        }}
    monkeypatch.setattr("swebench.harness.run_evaluation.run_instance", grade)
    args = argparse.Namespace(
        mode="predictions", network="default", retries=1, docker_timeout=5, timeout=5,
        workers=1, resume=False,
    )
    rows = [{"instance_id": "task"}, {"instance_id": "empty"}]
    predictions = {
        iid: {"model_name_or_path": "model", "model_patch": patch}
        for iid, patch in (("task", "patch"), ("empty", ""))
    }
    report = script.evaluate(args, rows, predictions)
    assert report["resolved"] == 1
    assert [r["status"] for r in report["instances"]] == ["resolved", "empty_patch"]
    assert report["instances"][0]["attempts"] == 2
    assert (tmp_path / "instances/task.json").is_file()
    args.resume = True
    docker.from_env.reset_mock()
    assert script.evaluate(args, rows, predictions)["resolved"] == 1
    docker.from_env.assert_not_called()

    docker.from_env.side_effect = ConnectionError("connection refused")
    predictions["failed"] = predictions["task"]
    report = script.evaluate(args, [*rows, {"instance_id": "failed"}], predictions)
    assert report["total"] == 3 and report["resolved"] == 1
    assert report["instances"][-1]["status"] == "evaluation_error"
    assert report["instances"][-1]["attempts"] == 2
    assert (tmp_path / "instances/failed.json").is_file()


def test_evaluation_injects_pip_no_build_isolation_env(monkeypatch, tmp_path):
    docker = pytest.importorskip("docker")
    pytest.importorskip("swebench")

    script = load_script("run_swebench_eval")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:12345")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)

    captured_kwargs = []
    client = Mock()
    client.containers.create.side_effect = lambda *a, **kw: captured_kwargs.append(kw)
    monkeypatch.setattr(docker, "from_env", Mock(return_value=client))
    monkeypatch.setattr(
        "swebench.harness.utils.make_test_spec",
        lambda row: SimpleNamespace(instance_id=row["instance_id"], image="image"),
    )

    def grade(spec, prediction, docker_client, *args, **kwargs):
        docker_client.containers.create("image")
        docker_client.containers.create("image", environment={"FOO": "bar"})
        docker_client.containers.create("image", environment=["PIP_NO_BUILD_ISOLATION=0", "FOO=bar"])
        return spec.instance_id, {spec.instance_id: {
            "resolved": True, "tests_status": {"FAIL_TO_PASS": {}, "PASS_TO_PASS": {}},
        }}

    monkeypatch.setattr("swebench.harness.run_evaluation.run_instance", grade)
    args = argparse.Namespace(
        mode="predictions", network="default", retries=0, docker_timeout=5, timeout=5,
        workers=1, resume=False, pip_no_build_isolation=True,
    )
    rows = [{"instance_id": "mpl_task"}]
    predictions = {"mpl_task": {"model_name_or_path": "model", "model_patch": "patch"}}
    report = script.evaluate(args, rows, predictions)
    assert report["resolved"] == 1
    assert captured_kwargs[0]["environment"]["PIP_NO_BUILD_ISOLATION"] == "1"
    assert captured_kwargs[0]["environment"]["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
    assert captured_kwargs[1]["environment"] == {
        "PIP_NO_BUILD_ISOLATION": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "FOO": "bar",
    }
    assert captured_kwargs[2]["environment"] == [
        "PIP_NO_BUILD_ISOLATION=0",
        "FOO=bar",
        "PIP_DISABLE_PIP_VERSION_CHECK=1",
    ]


def test_batch_resumes_errors_without_duplicates(monkeypatch, tmp_path):
    script = load_script("run_agent_batch")
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("".join(json.dumps({
        "instance_id": iid, "base_commit": "a" * 40, "image": "image", "problem_statement": iid,
    }) + "\n" for iid in ("first", "second")))
    output = tmp_path / "run"
    argv = ["batch", "--dataset", str(dataset), "--output-dir", str(output),
            "--max-steps", "45", "--max-cost", "0.7", "--workers", "2"]
    monkeypatch.setenv("LLM_API_KEY", "test")
    executed = []
    def run(instance, llm, cfg, output, *flags):
        assert cfg.max_steps == 45 and cfg.max_cost_usd == 0.7 and not cfg.sandbox.pipefail
        iid = instance.instance_id
        status = "error" if iid == "second" and iid not in executed else "finished"
        executed.append(iid)
        return Prediction(iid, cfg.llm.model, "diff"), {
            "instance_id": iid, "status": status, "steps": 1, "total_cost_usd": 0, "patch_chars": 4,
        }
    monkeypatch.setattr(script, "run_instance", run)
    monkeypatch.setattr("sys.argv", argv)
    assert script.main() == 1
    monkeypatch.setattr("sys.argv", argv + ["--resume"])
    assert script.main() == 0
    assert executed.count("first") == 1 and executed.count("second") == 2
    for name in ("results", "predictions"):
        rows = script.read_jsonl(output / f"{name}.jsonl")
        assert [r["instance_id"] for r in rows] == ["first", "second"]


def test_verification_evidence_is_invalidated_by_new_edits():
    runtime = Mock()
    runtime.file_exists.return_value = True
    runtime.git_diff.return_value = ""
    runtime.run_command.return_value = CommandResult("FAILED test_number.py", "", 1, 10)
    gate = VerificationGate(runtime, ["tests/test_number.py"], "")
    assert "no patch" in gate.finish_issue()
    assert gate.run_test("tests/test_number.py").exit_code == 1
    runtime.git_diff.return_value = "diff version 1"
    runtime.run_command.return_value = CommandResult("1 passed", "", 0, 10)
    assert "test_number.py" in gate.finish_issue()
    gate.run_test("tests/test_number.py")
    assert not gate.finish_issue()
    runtime.git_diff.return_value = "diff version 2"
    assert "test_number.py" in gate.finish_issue()


def test_context_compacts_completed_tool_turns_and_preserves_prefix():
    runtime = Mock()
    runtime.git_diff.return_value = "+++ b/code.py\n"
    runtime.run_command.return_value = CommandResult("x" * 1600, "", 0, 10)
    cfg = HarnessConfig(context=ContextConfig(auto_compact=True, compaction_trigger_tokens=150))
    llm = MockLLMClient([
        LLMResponse(tool_calls=[ToolCallRequest("a", "run_command", {"command": "test"})]),
        LLMResponse(tool_calls=[ToolCallRequest("b", "run_command", {"command": "check"})]),
        LLMResponse(content="finished"),
    ])
    controller = AgentController(llm, runtime, build_default_tool_registry(runtime), config=cfg)
    controller.run("fix problem")
    assert len(llm.calls[-1]["messages"]) == 4
    assert llm.calls[-1]["messages"][:2] == llm.calls[0]["messages"]
    assert "code.py" in llm.calls[-1]["messages"][2]["content"]
    assert any(e.event_type == EventType.COMPACTION for e in controller.event_stream.events)


def test_ranked_map_follows_symbol_references(tmp_path):
    pytest.importorskip("tree_sitter")
    pytest.importorskip("tree_sitter_python")
    pytest.importorskip("networkx")
    pytest.importorskip("scipy")
    (tmp_path / "unrelated.py").write_text("def ignored(): pass\n")
    (tmp_path / "handler.py").write_text("def requested_flow():\n    return important_helper()\n")
    (tmp_path / "logic.py").write_text("def important_helper(): pass\n")
    result = RepoMapper(LocalWorkspaceRuntime(tmp_path)).build_ranked_map(query="requested_flow", max_tokens=32)
    assert "logic.py:" in result and "unrelated.py:" in result
    assert result.index("logic.py:") < result.index("unrelated.py:")
    assert "important_helper" in result
    assert len(result) <= 128


def test_optional_loop_recovery_allows_a_different_action():
    runtime = Mock()
    runtime.run_command.return_value = CommandResult("ok", "", 0, 1)
    runtime.git_diff.return_value = ""
    llm = MockLLMClient([
        LLMResponse(tool_calls=[ToolCallRequest(str(i), "run_command", {"command": command})])
        for i, command in enumerate(["same", "same", "same", "different"])
    ] + [LLMResponse(content="done")])
    controller = AgentController(
        llm, runtime, build_default_tool_registry(runtime),
        config=HarnessConfig(recover_tool_loops=True),
    )
    assert controller.run("fix it").status == "finished"
    assert runtime.run_command.call_count == 3
    assert any("This call was skipped" in e.payload.get("content", "")
               for e in controller.event_stream.events if e.event_type == EventType.ERROR)
