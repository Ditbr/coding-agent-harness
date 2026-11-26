"""Unit tests for SandboxRuntime guardrails and ACI tools."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from harness.config import SandboxConfig
from harness.runtime.base import truncate_head_tail
from harness.runtime.docker import DockerSandboxRuntime
from harness.runtime.local import LocalWorkspaceRuntime
from harness.tools.aci import build_default_tool_registry


class TestACIToolsAndRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True, capture_output=True)

        (self.repo / "calc.py").write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a - b  # intentional bug   \n"
            "\n"
            "def mul(a: int, b: int) -> int:\n"
            "    return a * b\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo, check=True, capture_output=True)

        self.runtime = LocalWorkspaceRuntime(self.repo, SandboxConfig(max_output_chars=200))
        self.runtime.start()
        self.tools = build_default_tool_registry(self.runtime)

    def tearDown(self) -> None:
        self.runtime.stop()
        self._tmp.cleanup()

    def test_view_file_numbered_window(self) -> None:
        obs = self.tools.execute("view_file", {"path": "calc.py", "start_line": 1, "end_line": 3})
        self.assertEqual(obs.status, "ok")
        self.assertIn("L0001 | def add(a: int, b: int) -> int:", obs.content)
        self.assertIn("lines 1-3 of 5", obs.content)

    def test_path_escape_blocked(self) -> None:
        obs = self.tools.execute("view_file", {"path": "../../etc/passwd"})
        self.assertEqual(obs.status, "error")

    def test_search_code_finds_matches(self) -> None:
        for path in (".", "calc.py"):
            with self.subTest(path=path):
                obs = self.tools.execute("search_code", {"query": "intentional bug", "path": path})
                self.assertEqual(obs.status, "ok")
                self.assertIn("calc.py", obs.content)
                self.assertIn("L0002", obs.content)

    def test_edit_file_level2_whitespace_and_ast_guardrail(self) -> None:
        # Invalid Python syntax must be rolled back automatically
        bad = self.tools.execute("edit_file", {
            "path": "calc.py",
            "old_str": "    return a - b  # intentional bug",  # trailing spaces omitted -> tests Level 2 too
            "new_str": "    return a +",  # SyntaxError
        })
        self.assertEqual(bad.status, "error")
        self.assertIn("SyntaxError", bad.content)
        self.assertIn("return a - b", self.runtime.read_file("calc.py"))

        # Valid fix using Level-2 trailing-whitespace-tolerant matching succeeds
        good = self.tools.execute("edit_file", {
            "path": "calc.py",
            "old_str": "    return a - b  # intentional bug",
            "new_str": "    return a + b",
        })
        self.assertEqual(good.status, "ok")
        self.assertIn("AST check passed", good.content)
        self.assertIn("return a + b", self.runtime.read_file("calc.py"))

    def test_checkpoint_and_rollback(self) -> None:
        self.runtime.checkpoint("before_edit")
        self.runtime.write_file("calc.py", "broken = True\n")
        self.assertIn("broken = True", self.runtime.read_file("calc.py"))
        self.runtime.rollback("before_edit")
        self.assertIn("def add", self.runtime.read_file("calc.py"))

    def test_truncate_head_tail_preserves_bottom_trace(self) -> None:
        text = "START_MARKER\n" + ("x" * 500) + "\nBOTTOM_EXCEPTION: ValueError"
        out, truncated = truncate_head_tail(text, max_chars=120)
        self.assertTrue(truncated)
        self.assertIn("START_MARKER", out)
        self.assertIn("BOTTOM_EXCEPTION: ValueError", out)

    def test_docker_runtime_hardened_flags(self) -> None:
        drt = DockerSandboxRuntime(image="python:3.11-slim")
        args = drt.build_run_args()
        self.assertIn("--network", args)
        self.assertIn("none", args)
        self.assertIn("--cap-drop=ALL", args)
        self.assertIn("--pids-limit", args)


if __name__ == "__main__":
    unittest.main()
