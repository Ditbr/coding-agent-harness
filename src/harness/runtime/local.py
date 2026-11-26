"""Local filesystem & stateless subprocess runtime for development and unit tests."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from harness.config import SandboxConfig
from harness.runtime.base import CommandResult, SandboxRuntime, truncate_head_tail

IGNORED_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}


class LocalWorkspaceRuntime(SandboxRuntime):
    """Executes commands statelessly inside a local directory with path-escape protection."""

    def __init__(self, workspace_root: Path | str, config: SandboxConfig | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.config = config or SandboxConfig(backend="local")
        self._checkpoints: dict[str, str] = {}

    def start(self) -> None:
        if not self.workspace_root.exists():
            raise FileNotFoundError(f"Workspace does not exist: {self.workspace_root}")

    def stop(self) -> None:
        return None

    def _resolve_safe(self, rel_path: str) -> Path:
        candidate = (self.workspace_root / rel_path).resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionError(f"Path escapes workspace root: {rel_path}") from exc
        return candidate

    def run_command(self, command: str, timeout: int | None = None) -> CommandResult:
        effective_timeout = timeout or self.config.cmd_timeout_seconds
        start_ts = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(
                ["bash", "-lc", command],
                cwd=self.workspace_root,
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
        target = self._resolve_safe(rel_path)
        return target.read_text(encoding="utf-8")

    def write_file(self, rel_path: str, content: str) -> None:
        target = self._resolve_safe(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def file_exists(self, rel_path: str) -> bool:
        try:
            return self._resolve_safe(rel_path).is_file()
        except PermissionError:
            return False

    def list_files(self, rel_dir: str = ".") -> list[str]:
        base = self._resolve_safe(rel_dir)
        files: list[str] = []
        for root, dirs, filenames in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
            for fname in sorted(filenames):
                full = Path(root) / fname
                files.append(full.relative_to(self.workspace_root).as_posix())
        return files

    def git_diff(self) -> str:
        res = self.run_command("git diff", timeout=30)
        return res.stdout

    def checkpoint(self, label: str) -> str:
        diff = self.git_diff()
        self._checkpoints[label] = diff
        return diff

    def rollback(self, label: str) -> None:
        if label not in self._checkpoints:
            raise KeyError(f"Unknown checkpoint: {label}")
        reset_res = self.run_command("git checkout -- . && git clean -fd", timeout=30)
        if reset_res.exit_code != 0:
            raise RuntimeError(f"Failed to reset working tree: {reset_res.combined_output}")
        saved_patch = self._checkpoints[label]
        if saved_patch.strip():
            proc = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "-"],
                cwd=self.workspace_root,
                input=saved_patch,
                text=True,
                capture_output=True,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"Failed to restore checkpoint '{label}': {proc.stderr}")
