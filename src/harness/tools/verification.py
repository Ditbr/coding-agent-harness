"""Track reproduction and test evidence for the patch being submitted."""

from __future__ import annotations

import ast
import hashlib
import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from harness.events.schema import Observation
from harness.runtime.base import CommandResult, SandboxRuntime

TEST_PASS = re.compile(
    r"\b[1-9]\d* passed\b",
    re.MULTILINE,
)
UNITTEST_PASS = re.compile(r"^OK(?:[ \t]*\([^\n]*\))?[ \t]*$", re.MULTILINE)
UNITTEST_RUN = re.compile(r"^Ran ([1-9]\d*) tests?\b", re.MULTILINE)
TEST_FAILURE = re.compile(
    r"^\s*(?:FAILED\b|FAIL:|ERROR(?:\s|:))|\b[1-9]\d* (?:failed|errors?)\b"
    r"|\btests? failed\b|^Traceback \(most recent call last\):|^exit=[1-9]\d*\b",
    re.IGNORECASE | re.MULTILINE,
)
TEST_SELECTION_OPTIONS = {
    "-k", "-m", "-o", "-c", "-p", "-t", "--settings", "--parallel", "--verbosity",
    "--rootdir", "--tb", "--maxfail", "--durations",
}
SHELL_BOUNDARIES = {";", "&&", "||", "|", "|&", "&", ";;"}
OUTPUT_COMMANDS = {"cat", "grep", "head", "sed", "tail"}
REDIRECTIONS = {">", ">>", "<", ">&", "<&", "&>"}
SOURCE_EXTENSIONS = {".py", ".pyi", ".pyx", ".pxd", ".c", ".cc", ".cpp", ".h", ".hpp"}
NON_SOURCE_DIRS = {"test", "tests", "testing", "benchmarks", "docs", "examples"}
TEMPORARY_FILE = re.compile(
    r"^_?(?:repro(?:duce)?|scratch|tmp|debug|verify)(?:[_.-]|\d|$)", re.IGNORECASE,
)


def _sympy_test_arguments(script: str) -> tuple[str, ...] | None:
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "sympy"
            and node.func.attr == "test"
        ):
            return tuple(arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str))
    return None


def _runner_arguments(words: list[str]) -> tuple[str, ...] | None:
    if not words:
        return None
    program = words[0]
    args = words[1:]
    if re.fullmatch(r"python(?:\d+(?:\.\d+)?)?", PurePosixPath(program).name):
        while args and args[0] in {"-b", "-bb", "-B", "-u", "-Werror"}:
            args = args[1:]
        if args[:2] in (["-m", "pytest"], ["-m", "unittest"]):
            return tuple(args[2:])
        if len(args) >= 2 and args[0] == "-c":
            return _sympy_test_arguments(args[1])
        if not args:
            return None
        program, args = args[0], args[1:]
    if (
        PurePosixPath(program).name in {"runtests.py", "pytest", "py.test"}
        or program.removeprefix("/testbed/").removeprefix("./") == "bin/test"
    ):
        return tuple(args)
    return None


def _test_selection(command: str) -> tuple[str, ...] | None:
    # Recognize actual shell command positions so grep/echo strings do not count as tests.
    # Treat output filters as part of the command only when they cannot hide a test exit code.
    lexer = shlex.shlex(command.replace("\\\n", " "), posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    commands: list[tuple[list[str], str]] = []
    try:
        words: list[str] = []
        for token in lexer:
            if token in {"<<", "<<<", "<<-"}:
                return None
            if token in REDIRECTIONS:
                if words and words[-1] in {"0", "1", "2"}:
                    words.pop()
                next(lexer, None)
                continue
            if token in SHELL_BOUNDARIES:
                commands.append((words, token))
                words = []
            else:
                words.append(token)
        commands.append((words, ""))
    except ValueError:
        return None
    for index, (words, separator) in enumerate(commands):
        while words and re.match(r"^[A-Za-z_]\w*=", words[0]):
            words = words[1:]
        args = _runner_arguments(words)
        if args is None:
            continue
        if any(separator in {"||", "&"} for _, separator in commands[index:]):
            return None
        if separator == ";" and (index + 1 == len(commands) or commands[index + 1][0] != ["echo", "exit=$?"]):
            return None
        if any(
            not later or (PurePosixPath(later[0]).name not in OUTPUT_COMMANDS and later != ["echo", "exit=$?"])
            for later, _ in commands[index + 1:]
        ):
            return None
        targets = []
        skip = False
        for arg in args:
            if skip:
                skip = False
                continue
            if arg in TEST_SELECTION_OPTIONS:
                skip = True
            elif arg != "discover" and not arg.startswith("-"):
                targets.append(arg)
        return tuple(targets)
    return None


def _is_test_path(path: PurePosixPath) -> bool:
    return (
        bool(set(path.parts[:-1]) & {"test", "tests", "testing"})
        or path.name in {"conftest.py", "test.py"}
        or path.stem.startswith("test_")
        or path.stem.endswith("_test")
    )


def _is_artifact(path: PurePosixPath) -> bool:
    return (
        bool({part.lower() for part in path.parts} & {"changelog", "changes", "news", "newsfragments"})
        or path.stem.lower() == "changelog"
        or bool(TEMPORARY_FILE.match(path.name))
    )


def _is_source_path(path: PurePosixPath) -> bool:
    return (
        path.suffix in SOURCE_EXTENSIONS and not _is_test_path(path) and not _is_artifact(path)
        and not (set(path.parts[:-1]) & NON_SOURCE_DIRS)
    )


def _decode_git_path(raw: str) -> str:
    raw = raw.split("\t", 1)[0]
    if raw.startswith('"'):
        return ast.literal_eval(raw).encode("latin-1").decode("utf-8", errors="replace")
    return raw


@dataclass
class PatchChanges:
    source: str = ""
    existing_tests: set[str] = field(default_factory=set)
    new_artifacts: set[str] = field(default_factory=set)


def _patch_changes(patch: str) -> PatchChanges:
    """Classify diff sections by their workspace paths, before any hunk content."""
    changes = PatchChanges()
    source = []
    for section in re.split(r"(?=^diff --git )", patch, flags=re.MULTILINE):
        headers = section.split("\n@@", 1)[0].splitlines()
        paths: set[str] = set()
        added = any(line.startswith("new file mode ") or line == "--- /dev/null" for line in headers)
        for line in headers:
            if line.startswith(("--- ", "+++ ")) and line[4:] != "/dev/null":
                paths.add(_decode_git_path(line[4:])[2:])
            elif line.startswith(("rename from ", "rename to ")):
                paths.add(_decode_git_path(line.split(" ", 2)[2]))
        if not paths and headers and headers[0].startswith("diff --git "):
            names = re.fullmatch(r'(a/.+) (b/.+)|("a/.+") ("b/.+")', headers[0][11:])
            if names:
                paths.update(_decode_git_path(name)[2:] for name in names.groups() if name)
        for name in paths:
            path = PurePosixPath(name)
            if added and _is_artifact(path):
                changes.new_artifacts.add(name)
            elif not added and _is_test_path(path):
                changes.existing_tests.add(name)
        if any(_is_source_path(PurePosixPath(path)) for path in paths):
            source.append(section)
    changes.source = "".join(source)
    return changes


class VerificationGate:
    def __init__(self, runtime: SandboxRuntime, repo: str) -> None:
        self.runtime = runtime
        self.repo = repo
        self.reproductions: set[tuple[str, ...]] = set()
        self.verified_patch: str | None = None
        runtime.checkpoint("baseline")

    def record_edit(self, path: str) -> None:
        if _is_source_path(PurePosixPath(path)):
            self.verified_patch = None

    def _execute_test(
        self, command: str, targets: tuple[str, ...], timeout: int,
    ) -> tuple[CommandResult, dict]:
        source = _patch_changes(self.runtime.git_diff()).source
        result = self.runtime.run_command(command, timeout=timeout)
        output = result.combined_output
        failed = bool(TEST_FAILURE.search(output))
        ran = UNITTEST_RUN.search(output)
        passed = result.exit_code == 0 and not failed and (
            TEST_PASS.search(output)
            or ran and UNITTEST_PASS.search(output) and not re.search(rf"^OK \(skipped={ran[1]}\)$", output, re.MULTILINE)
        )
        outcome = "inconclusive"
        if not result.timed_out:
            if failed:
                outcome = "failed"
                if not source:
                    self.reproductions.add(targets)
                elif self.verified_patch == self.patch_digest(source):
                    self.verified_patch = None
            elif passed:
                outcome = "passed"
                if source and source == _patch_changes(self.runtime.git_diff()).source:
                    self.verified_patch = self.patch_digest(source)
        return result, {
            "test": True,
            "test_result": outcome,
            "targets": list(targets),
            "baseline_reproduction": targets in self.reproductions,
        }

    def run_command(self, command: str, timeout: int) -> tuple[CommandResult, dict]:
        targets = _test_selection(command)
        if targets is None:
            return self.runtime.run_command(command, timeout=timeout), {}
        return self._execute_test(command, targets, timeout)

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
        result, evidence = self._execute_test(shlex.join(command), (target,), timeout)
        evidence["target"] = target
        return Observation(
            "run_test", "ok" if result.exit_code == 0 else "error",
            f"exit_code={result.exit_code} duration_ms={result.duration_ms}\n{result.combined_output}",
            exit_code=result.exit_code, truncated=result.truncated, metadata=evidence,
        )

    @staticmethod
    def patch_digest(patch: str) -> str:
        return hashlib.sha256(patch.encode("utf-8")).hexdigest()

    def finish_issue(self) -> str:
        patch = self.runtime.git_diff()
        if not patch.strip():
            return "The working tree has no patch. Apply a fix before finishing."
        changes = _patch_changes(patch)
        if changes.existing_tests or changes.new_artifacts:
            actions = []
            if changes.existing_tests:
                actions.append("git restore --staged --worktree -- " + shlex.join(sorted(changes.existing_tests)))
            if changes.new_artifacts:
                names = shlex.join(sorted(changes.new_artifacts))
                actions.append(f"git rm --cached --ignore-unmatch -- {names} && rm -f -- {names}")
            return "Restore modified existing tests or remove temporary files before finishing. Run: " + " && ".join(actions)
        if not changes.source:
            return "The patch needs a change to non-test production code before finishing."
        if self.verified_patch != self.patch_digest(changes.source):
            return "Run a relevant test successfully against the current source patch before finishing."
        return ""
