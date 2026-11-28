"""Abstract SandboxRuntime contract and shared output truncation utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Self

from harness.runtime.search import search_files


def truncate_head_tail(text: str, max_chars: int = 8000, head_ratio: float = 0.30) -> tuple[str, bool]:
    """Keep 30% head + 70% tail so stack traces at the bottom are preserved."""
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    head_len = max(1, int(max_chars * head_ratio))
    tail_len = max(1, max_chars - head_len)
    omitted = len(text) - head_len - tail_len
    marker = f"\n\n... [truncated {omitted} chars; kept head {head_len} & tail {tail_len} chars] ...\n\n"
    return text[:head_len] + marker + text[-tail_len:], True


@dataclass(slots=True)
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool = False
    truncated: bool = False

    @property
    def combined_output(self) -> str:
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(f"[stderr]\n{self.stderr}")
        return "\n".join(parts).strip()


class SandboxRuntime(ABC):
    """Unified stateless execution interface decoupling AgentController from host/Docker."""

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    @abstractmethod
    def start(self) -> None:
        """Prepare or spin up the isolated workspace."""

    @abstractmethod
    def stop(self) -> None:
        """Tear down and release sandbox resources."""

    @abstractmethod
    def run_command(self, command: str, timeout: int | None = None) -> CommandResult:
        """Execute a stateless shell command in the repository root."""

    @abstractmethod
    def read_file(self, rel_path: str) -> str:
        """Read UTF-8 file contents relative to repository root."""

    @abstractmethod
    def write_file(self, rel_path: str, content: str) -> None:
        """Write UTF-8 file contents relative to repository root."""

    @abstractmethod
    def file_exists(self, rel_path: str) -> bool:
        """Check whether a file exists relative to repository root."""

    @abstractmethod
    def list_files(self, rel_dir: str = ".") -> list[str]:
        """List repository files relative to workspace root (excluding .git)."""

    def python_sources(self) -> Iterator[tuple[str, str]]:
        for path in self.list_files("."):
            if path.endswith(".py"):
                try:
                    yield path, self.read_file(path)
                except (OSError, UnicodeError):
                    continue

    def search(self, query: str, path: str, file_glob: str, max_matches: int) -> tuple:
        return search_files(query, file_glob, self.list_files(path), self.read_file, max_matches)

    @abstractmethod
    def git_diff(self) -> str:
        """Return the current git diff against the repository base commit."""

    @abstractmethod
    def checkpoint(self, label: str) -> str:
        """Save current working-tree diff under a checkpoint label."""

    @abstractmethod
    def rollback(self, label: str) -> None:
        """Restore working tree to a previously saved checkpoint."""
