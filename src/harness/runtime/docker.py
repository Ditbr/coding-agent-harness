"""Docker container sandbox runtime with network, memory, CPU, and PID isolation."""

from __future__ import annotations

import base64
import shlex
import subprocess
import time
import uuid

from harness.config import SandboxConfig
from harness.runtime.base import CommandResult, SandboxRuntime, truncate_head_tail


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
    ) -> None:
        self.config = config or SandboxConfig(backend="docker")
        self.image = image or self.config.docker_image
        self.workdir = workdir
        self.host_mount = host_mount
        self.container_name = f"coding-harness-{uuid.uuid4().hex[:10]}"
        self._container_id: str | None = None
        self._checkpoints: dict[str, str] = {}

    def build_run_args(self) -> list[str]:
        """Construct hardened `docker run` arguments (exposed for testability)."""
        args = [
            "docker", "run", "-d", "--rm",
            "--name", self.container_name,
            "--workdir", self.workdir,
            "--memory", self.config.memory_limit,
            "--memory-swap", self.config.memory_limit,
            "--cpus", str(self.config.cpu_cores),
            "--pids-limit", str(self.config.pids_limit),
            "--cap-drop=ALL",
        ]
        if self.config.network_disabled:
            args.extend(["--network", "none"])
        if self.host_mount:
            args.extend(["-v", f"{self.host_mount}:{self.workdir}"])
        args.extend([self.image, "sleep", "infinity"])
        return args

    def start(self) -> None:
        proc = subprocess.run(self.build_run_args(), capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"Failed to start Docker sandbox: {proc.stderr.strip()}")
        self._container_id = proc.stdout.strip()

    def stop(self) -> None:
        if not self._container_id:
            return
        subprocess.run(
            ["docker", "rm", "-f", self._container_id],
            capture_output=True,
            text=True,
            check=False,
        )
        self._container_id = None

    def _require_started(self) -> str:
        if not self._container_id:
            raise RuntimeError("DockerSandboxRuntime is not started.")
        return self._container_id

    def run_command(self, command: str, timeout: int | None = None) -> CommandResult:
        cid = self._require_started()
        effective_timeout = timeout or self.config.cmd_timeout_seconds
        start_ts = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                ["docker", "exec", "-w", self.workdir, cid, "bash", "-lc", command],
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=False,
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            stderr = f"{stderr}\nCommand timed out after {effective_timeout}s.".strip()
            exit_code = 124

        duration_ms = int((time.monotonic() - start_ts) * 1000)
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

    def read_file(self, rel_path: str) -> str:
        res = self.run_command(f"cat {shlex.quote(rel_path)}", timeout=30)
        if res.exit_code != 0:
            raise FileNotFoundError(f"Failed to read {rel_path}: {res.stderr}")
        return res.stdout

    def write_file(self, rel_path: str, content: str) -> None:
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = (
            f"python3 -c 'import base64, pathlib; "
            f"p = pathlib.Path({rel_path!r}); p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_bytes(base64.b64decode({encoded!r}))'"
        )
        res = self.run_command(cmd, timeout=30)
        if res.exit_code != 0:
            raise RuntimeError(f"Failed to write {rel_path}: {res.stderr}")

    def file_exists(self, rel_path: str) -> bool:
        return self.run_command(f"test -f {shlex.quote(rel_path)}", timeout=10).exit_code == 0

    def list_files(self, rel_dir: str = ".") -> list[str]:
        res = self.run_command(
            f"find {shlex.quote(rel_dir)} -path '*/.git' -prune -o -type f -print | sort",
            timeout=30,
        )
        return [ln.lstrip("./") for ln in res.stdout.splitlines() if ln.strip()]

    def git_diff(self) -> str:
        return self.run_command("git diff", timeout=30).stdout

    def checkpoint(self, label: str) -> str:
        diff = self.git_diff()
        self._checkpoints[label] = diff
        return diff

    def rollback(self, label: str) -> None:
        if label not in self._checkpoints:
            raise KeyError(f"Unknown checkpoint: {label}")
        self.run_command("git checkout -- . && git clean -fd", timeout=30)
        patch = self._checkpoints[label]
        if patch.strip():
            encoded = base64.b64encode(patch.encode("utf-8")).decode("ascii")
            self.run_command(
                f"echo {shlex.quote(encoded)} | base64 -d | git apply --whitespace=nowarn -",
                timeout=30,
            )
