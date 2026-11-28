"""Docker container sandbox runtime with network, memory, CPU, and PID isolation."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from harness.config import SandboxConfig
from harness.runtime.base import CommandResult, SandboxRuntime, truncate_head_tail
from harness.runtime.docker_env import docker_environment


class DockerSandboxRuntime(SandboxRuntime):
    """Hardened Docker runtime executing stateless commands via `docker exec`.

    Security guardrails enforced by default:
    - `--network=none` (offline reproducibility & SSRF prevention)
    - `--memory` & `--memory-swap` caps (OOM protection)
    - `--cpus` & `--pids-limit` caps (fork-bomb & CPU saturation protection)
    - `--cap-drop=ALL` (least privilege)
    """

    def __init__(
        self,
        image: str | None = None,
        workdir: str = "/testbed",
        config: SandboxConfig | None = None,
        host_mount: str | None = None,
        platform: str | None = None,
        base_commit: str | None = None,
    ) -> None:
        self.config = config or SandboxConfig(backend="docker")
        self.image = image or self.config.docker_image
        self.workdir = workdir
        self.host_mount = host_mount
        self.platform = platform
        self.base_commit = base_commit
        self.container_name = f"coding-harness-{uuid.uuid4().hex[:10]}"
        self._container_id: str | None = None
        self._patch_base = "HEAD"
        self._checkpoints: dict[str, str] = {}

    def build_run_args(self) -> list[str]:
        """Construct hardened `docker run` arguments (exposed for testability)."""
        args = [
            "docker", "run", "-d", "--rm", "--init",
            "--name", self.container_name,
            "--workdir", self.workdir,
            "--memory", self.config.memory_limit,
            "--memory-swap", self.config.memory_limit,
            "--cpus", str(self.config.cpu_cores),
            "--pids-limit", str(self.config.pids_limit),
            "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--env", "LANG=C.UTF-8",
            "--env", "LC_ALL=C.UTF-8",
            "--env", "PYTHONIOENCODING=utf-8",
            "--entrypoint", "/bin/sleep",
        ]
        if self.platform:
            args.extend(["--platform", self.platform])
        if self.config.network_disabled:
            args.extend(["--network", "none"])
        if self.host_mount:
            args.extend(["-v", f"{self.host_mount}:{self.workdir}"])
        args.extend([self.image, "infinity"])
        return args

    def start(self) -> None:
        try:
            proc = subprocess.run(
                self.build_run_args(), capture_output=True, text=True, check=False,
                env=docker_environment(), timeout=self.config.cmd_timeout_seconds + 10,
            )
        except subprocess.TimeoutExpired as exc:
            self._remove(self.container_name)
            raise RuntimeError(f"Docker sandbox startup timed out: {self.container_name}") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to start Docker sandbox: {proc.stderr.strip()}")
        self._container_id = proc.stdout.strip()
        try:
            self._checked_command(
                "if command -v git >/dev/null; then "
                f"git config --global --add safe.directory {shlex.quote(self.workdir)}; fi"
            )
            if self.base_commit:
                actual, parents, subject = self._checked_command(
                    "git log -1 --format='%H%n%P%n%s'",
                ).splitlines()
                if actual != self.base_commit and (parents, subject) != (self.base_commit, "SWE-bench"):
                    raise RuntimeError(f"Image HEAD {actual} differs from expected {self.base_commit}")
                # Published images may commit benchmark test-file removal on top of base_commit.
                self._patch_base = actual
        except BaseException:
            self.stop()
            raise

    def stop(self) -> None:
        if not self._container_id:
            return
        self._remove(self._container_id)
        self._container_id = None

    @staticmethod
    def _remove(container: str) -> None:
        try:
            subprocess.run(
                ["docker", "rm", "-f", container], capture_output=True, text=True,
                check=False, env=docker_environment(), timeout=10,
            )
        except subprocess.TimeoutExpired:
            return

    def _require_started(self) -> str:
        if not self._container_id:
            raise RuntimeError("DockerSandboxRuntime is not started.")
        return self._container_id

    def run_command(self, command: str, timeout: int | None = None) -> CommandResult:
        return self._execute(command, timeout or self.config.cmd_timeout_seconds)

    def _execute(
        self, command: str, timeout: int, *, full_output: bool = False, stdin: str | None = None,
    ) -> CommandResult:
        cid = self._require_started()
        start_ts = time.monotonic()
        timed_out = False
        args = ["docker", "exec", "-w", self.workdir]
        if stdin is not None:
            args.append("-i")
        shell_flags = "-o pipefail " if self.config.pipefail else ""
        args.extend([
            cid, "bash", "-c",
            (
                'export PATH="/opt/miniconda3/envs/testbed/bin:/opt/miniconda3/bin:$PATH"\n'
                f'exec timeout --verbose --signal=KILL "$1" bash {shell_flags}-c "$2"'
            ),
            "harness", str(timeout), command,
        ])
        try:
            proc = subprocess.run(
                args,
                input=stdin,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout + 10,
                check=False,
                env=docker_environment(),
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
            # GNU timeout kills the process group inside the container.
            timed_out = exit_code == 137 and "timeout: sending signal KILL to command" in stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or ""
            # The host CLI can lose its connection while the daemon and worktree remain healthy.
            stderr += "\nDocker exec did not return after its in-container deadline. Sandbox retained."
        if timed_out:
            stderr = f"{stderr}\nCommand timed out after {timeout}s.".strip()
            exit_code = 124

        duration_ms = int((time.monotonic() - start_ts) * 1000)
        if full_output:
            return CommandResult(stdout, stderr, exit_code, duration_ms, timed_out)
        stdout_t, t1 = truncate_head_tail(stdout, self.config.max_output_chars)
        stderr_t, t2 = truncate_head_tail(stderr, max(1000, self.config.max_output_chars // 2))
        return CommandResult(
            stdout=stdout_t,
            stderr=stderr_t,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
            truncated=t1 or t2,
        )

    def _checked_command(
        self, command: str, stdin: str | None = None, *, retry_timeout: bool = False,
    ) -> str:
        res = self._execute(command, 30, full_output=True, stdin=stdin)
        if retry_timeout and res.timed_out:
            res = self._execute(command, 30, full_output=True, stdin=stdin)
        if res.exit_code != 0:
            raise RuntimeError(res.combined_output or f"Command failed with exit code {res.exit_code}")
        return res.stdout

    def read_file(self, rel_path: str) -> str:
        res = self._execute(f"cat -- {shlex.quote(rel_path)}", 30, full_output=True)
        if res.exit_code != 0:
            raise FileNotFoundError(f"Failed to read {rel_path}: {res.stderr}")
        return res.stdout

    def write_file(self, rel_path: str, content: str) -> None:
        script = (
            "import pathlib, sys; p = pathlib.Path(sys.argv[1]); "
            "p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(sys.stdin.buffer.read())"
        )
        self._checked_command(f"python3 -c {shlex.quote(script)} {shlex.quote(rel_path)}", stdin=content)

    def file_exists(self, rel_path: str) -> bool:
        return self.run_command(f"test -f {shlex.quote(rel_path)}", timeout=10).exit_code == 0

    def list_files(self, rel_dir: str = ".") -> list[str]:
        paths = self._checked_command(
            f"find {shlex.quote(rel_dir)} -name .git -prune -o -type f -print0",
        )
        return sorted(path.removeprefix("./") for path in paths.split("\0") if path)

    def python_sources(self) -> Iterator[tuple[str, str]]:
        # Read tracked Python sources in one exec instead of a round trip per file.
        script = """
import json
import subprocess
from pathlib import Path

root = Path.cwd()
paths = subprocess.check_output(["git", "ls-files", "-z", "--", "*.py"]).split(b"\\0")
for raw_path in paths:
    if raw_path:
        name = raw_path.decode("utf-8", "replace")
        path = (root / name).resolve()
        try:
            path.relative_to(root)
            if path.is_file() and path.stat().st_size <= 1024 * 1024:
                print(json.dumps([name, path.read_text(encoding="utf-8")]))
        except (OSError, UnicodeError, ValueError):
            continue
"""
        result = self._execute(shlex.join(["python3", "-c", script]), 120, full_output=True)
        if result.exit_code:
            raise RuntimeError(f"Could not read Python sources: {result.stderr}")
        for line in result.stdout.splitlines():
            path, source = json.loads(line)
            yield path, source

    def search(self, query: str, path: str, file_glob: str, max_matches: int) -> tuple:
        script = Path(__file__).with_name("search.py").read_text(encoding="utf-8")
        command = shlex.join(["python3", "-c", script, query, path, file_glob, str(max_matches)])
        total, counts, excerpts = json.loads(self._checked_command(command))
        return total, counts, excerpts

    def git_diff(self) -> str:
        base = shlex.quote(self._patch_base)
        return self._checked_command(
            'set -e; temp_dir=$(mktemp -d); trap \'rm -rf "$temp_dir"\' EXIT; '
            'export GIT_INDEX_FILE="$temp_dir/index"; '
            f"git read-tree {base}; git add -A; git diff --cached --binary --no-ext-diff {base} --",
            retry_timeout=True,
        )

    def checkpoint(self, label: str) -> str:
        diff = self.git_diff() if self.base_commit else self._checked_command("git diff --binary")
        self._checkpoints[label] = diff
        return diff

    def rollback(self, label: str) -> None:
        if label not in self._checkpoints:
            raise KeyError(f"Unknown checkpoint: {label}")
        if self.base_commit:
            base = shlex.quote(self._patch_base)
            self._checked_command(f"git restore --source={base} --staged --worktree -- . && git clean -fd")
        else:
            self._checked_command("git checkout -- . && git clean -fd")
        patch = self._checkpoints[label]
        if patch.strip():
            self._checked_command("git apply --whitespace=nowarn -", stdin=patch)
