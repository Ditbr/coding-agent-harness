"""End-to-end test of AgentController solving a real bug in a temporary Git repository."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from harness.agent.controller import AgentController
from harness.config import HarnessConfig
from harness.events.schema import TokenUsage, ToolCallRequest
from harness.events.stream import EventStream, JsonlTrajectoryLogger
from harness.llm.client import LLMResponse, MockLLMClient
from harness.repomap.mapper import RepoMapper
from harness.runtime.local import LocalWorkspaceRuntime
from harness.tools.aci import build_default_tool_registry


class TestAgentLoopEndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True, capture_output=True)

        (self.repo / "math_utils.py").write_text(
            "def clamp(val: int, low: int, high: int) -> int:\n"
            "    if val < low:\n"
            "        return low\n"
            "    if val > high:\n"
            "        return low  # bug: should return high\n"
            "    return val\n",
            encoding="utf-8",
        )
        (self.repo / "test_math_utils.py").write_text(
            "import unittest\n"
            "from math_utils import clamp\n\n"
            "class TestClamp(unittest.TestCase):\n"
            "    def test_upper_bound(self):\n"
            "        self.assertEqual(clamp(15, 0, 10), 10)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo, check=True, capture_output=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_end_to_end_reproduce_fix_verify(self) -> None:
        scripted = [
            LLMResponse(
                content="Let me run the unit test first to reproduce the bug.",
                tool_calls=[ToolCallRequest("c1", "run_command", {"command": "python3 -m unittest test_math_utils.py"})],
                usage=TokenUsage(prompt_tokens=500, cached_tokens=0, completion_tokens=30, cost_usd=0.001),
            ),
            LLMResponse(
                content="Inspect math_utils.py around clamp().",
                tool_calls=[ToolCallRequest("c2", "view_file", {"path": "math_utils.py", "start_line": 1, "end_line": 20})],
                usage=TokenUsage(prompt_tokens=700, cached_tokens=500, completion_tokens=25, cost_usd=0.001),
            ),
            LLMResponse(
                content="Fix upper bound return value in clamp().",
                tool_calls=[ToolCallRequest("c3", "edit_file", {
                    "path": "math_utils.py",
                    "old_str": "    if val > high:\n        return low  # bug: should return high",
                    "new_str": "    if val > high:\n        return high",
                })],
                usage=TokenUsage(prompt_tokens=900, cached_tokens=700, completion_tokens=40, cost_usd=0.001),
            ),
            LLMResponse(
                content="Re-run unit tests to verify the fix.",
                tool_calls=[ToolCallRequest("c4", "run_command", {"command": "python3 -m unittest test_math_utils.py"})],
                usage=TokenUsage(prompt_tokens=1100, cached_tokens=900, completion_tokens=25, cost_usd=0.001),
            ),
            LLMResponse(
                content="Tests pass; finishing task.",
                tool_calls=[ToolCallRequest("c5", "finish", {"summary": "Fixed clamp() upper-bound return value and verified with unittest."})],
                usage=TokenUsage(prompt_tokens=1200, cached_tokens=1100, completion_tokens=30, cost_usd=0.001),
            ),
        ]

        with LocalWorkspaceRuntime(self.repo) as rt:
            repo_map = RepoMapper(rt).build_map()
            self.assertIn("def clamp", repo_map)

            traj_file = self.repo / ".traj_test.jsonl"
            stream = EventStream()
            stream.subscribe(JsonlTrajectoryLogger(traj_file))
            tools = build_default_tool_registry(rt)
            llm = MockLLMClient(scripted)
            controller = AgentController(llm=llm, runtime=rt, tools=tools, event_stream=stream, config=HarnessConfig())

            res = controller.run(
                task_prompt="clamp(15, 0, 10) returns 0 instead of 10.",
                instance_id="demo__clamp-1",
                repo_map=repo_map,
            )

            self.assertEqual(res.status, "finished")
            self.assertEqual(res.steps, 5)
            self.assertIn("-        return low  # bug: should return high", res.patch)
            self.assertIn("+        return high", res.patch)
            self.assertGreater(res.total_cached_tokens, 0)
            self.assertTrue(traj_file.exists())

    def test_loop_detection_stops_repeated_identical_calls(self) -> None:
        repeated = [
            LLMResponse(
                content="Retry same call",
                tool_calls=[ToolCallRequest(f"c{i}", "view_file", {"path": "missing.py"})],
            )
            for i in range(4)
        ]
        with LocalWorkspaceRuntime(self.repo) as rt:
            controller = AgentController(
                llm=MockLLMClient(repeated),
                runtime=rt,
                tools=build_default_tool_registry(rt),
                config=HarnessConfig(max_consecutive_duplicates=3),
            )
            res = controller.run(task_prompt="Trigger loop guardrail")
            self.assertEqual(res.status, "loop_detected")
            self.assertEqual(res.steps, 3)


if __name__ == "__main__":
    unittest.main()
