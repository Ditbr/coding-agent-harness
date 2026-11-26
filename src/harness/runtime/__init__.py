"""Execution runtime abstractions (local workspace and Docker container)."""

from harness.runtime.base import CommandResult, SandboxRuntime, truncate_head_tail
from harness.runtime.docker import DockerSandboxRuntime
from harness.runtime.local import LocalWorkspaceRuntime

__all__ = [
    "CommandResult",
    "DockerSandboxRuntime",
    "LocalWorkspaceRuntime",
    "SandboxRuntime",
    "truncate_head_tail",
]
