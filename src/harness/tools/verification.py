"""Track reproduction and test evidence for the patch being submitted."""

import hashlib
import re
import shlex

from harness.events.schema import Observation
from harness.runtime.base import SandboxRuntime

TEST_FAILURE = re.compile(r"\bFAILED\b|\bFAIL:|\b[1-9]\d* failed\b|\btest failed\b", re.IGNORECASE)


class VerificationGate:
    def __init__(self, runtime: SandboxRuntime, modules: list[str], repo: str) -> None:
        self.runtime = runtime
        self.repo = repo
        self.modules = {path for path in modules if runtime.file_exists(path)}
        self.reproductions: set[str] = set()
        self.verified: dict[str, set[str]] = {}
        runtime.checkpoint("baseline")

    def run_test(self, target: str, timeout: int = 120) -> Observation:
        if not re.fullmatch(r"[\w./-]+\.py", target) or target.startswith(("/", "-")) or ".." in target.split("/"):
            return Observation("run_test", "error", "Provide a repository-relative Python test file.")
        target = target.removeprefix("./")
        if not self.runtime.file_exists(target):
            return Observation("run_test", "error", f"Test file does not exist: {target}")
        if self.repo == "django/django" and target.startswith("tests/"):
            selector = target.removeprefix("tests/").removesuffix(".py").replace("/", ".")
            command = ["python", "tests/runtests.py", selector]
        elif self.repo == "sympy/sympy":
            command = ["python", "bin/test", target]
        else:
            command = ["python", "-m", "pytest", "-q", target]
        patch = self.runtime.git_diff()
        result = self.runtime.run_command(shlex.join(command), timeout=timeout)
        changes = self.changed_paths(patch)
        if (not patch.strip() or changes == {target}) and result.exit_code == 1 and (
            TEST_FAILURE.search(result.combined_output)
        ):
            self.reproductions.add(target)
        if patch.strip() and result.exit_code == 0 and patch == self.runtime.git_diff():
            self.verified.setdefault(self.patch_digest(patch), set()).add(target)
        return Observation(
            "run_test", "ok" if result.exit_code == 0 else "error",
            f"exit_code={result.exit_code} duration_ms={result.duration_ms}\n{result.combined_output}",
            exit_code=result.exit_code, truncated=result.truncated,
            metadata={"target": target, "test": True},
        )

    @staticmethod
    def changed_paths(patch: str) -> set[str]:
        return set(re.findall(r"^(?:--- a/|\+\+\+ b/)([^\t\n]+)", patch, re.MULTILINE))

    @staticmethod
    def patch_digest(patch: str) -> str:
        return hashlib.sha256(patch.encode("utf-8")).hexdigest()

    def finish_issue(self) -> str:
        patch = self.runtime.git_diff()
        if not patch.strip():
            return "The working tree has no patch. Apply a fix before finishing."
        edited_tests = self.modules & self.changed_paths(patch)
        if edited_tests:
            return "Restore the official test modules before submitting: " + ", ".join(sorted(edited_tests))
        if not self.reproductions:
            return (
                "Record a failing test on the baseline using run_test before submitting. "
                "Use checkpoint and rollback to preserve your work while checking the baseline."
            )
        verified = self.verified.get(self.patch_digest(patch), set())
        remaining = (self.modules or self.reproductions) - verified
        if remaining:
            return f"Run these test modules successfully against the current patch: {', '.join(sorted(remaining))}."
        return ""
