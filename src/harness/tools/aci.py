"""Orthogonal ACI (Agent-Computer Interface) tools with guardrails.

Implements:
1. view_file       - Windowed, line-numbered code viewer (max 150 lines/call)
2. search_code     - Aggregated regex search avoiding noisy output floods
3. edit_file       - SEARCH/REPLACE with 3-level tolerance + Python AST syntax guardrail
4. run_command     - Stateless shell execution with timeout & head/tail truncation
5. git_status_diff - Clean working-tree status & diff inspection
6. finish          - Explicit task completion signal
"""

from __future__ import annotations

import ast
from difflib import SequenceMatcher

from harness.events.schema import Observation
from harness.runtime.base import SandboxRuntime, truncate_head_tail
from harness.tools.registry import ToolRegistry, ToolSpec
from harness.tools.verification import VerificationGate

MAX_VIEW_LINES = 150
MAX_SEARCH_MATCHES = 30


def _format_numbered_lines(lines: list[str], start_idx_1based: int, end_idx_1based: int) -> str:
    rendered = []
    for lineno in range(start_idx_1based, end_idx_1based + 1):
        rendered.append(f"L{lineno:04d} | {lines[lineno - 1]}")
    return "\n".join(rendered)


def _find_whitespace_tolerant_span(lines: list[str], target_lines: list[str]) -> list[int]:
    """Level-2 matcher: ignore trailing whitespace differences line by line."""
    if not target_lines:
        return []
    norm_target = [ln.rstrip() for ln in target_lines]
    k = len(norm_target)
    hits: list[int] = []
    for idx in range(len(lines) - k + 1):
        window = [lines[idx + offset].rstrip() for offset in range(k)]
        if window == norm_target:
            hits.append(idx)
    return hits


def build_default_tool_registry(
    runtime: SandboxRuntime, *, verification_modules: list[str] | None = None,
    enable_checkpoints: bool = False, repo: str = "",
) -> ToolRegistry:
    registry = ToolRegistry()
    gate = VerificationGate(runtime, verification_modules, repo) if verification_modules is not None else None
    edit_feedback = enable_checkpoints or gate is not None

    def view_file(path: str, start_line: int = 1, end_line: int = 120) -> Observation:
        if not runtime.file_exists(path):
            return Observation(
                tool="view_file",
                status="error",
                content=f"File not found: '{path}'. Use search_code to locate the correct path.",
            )
        content = runtime.read_file(path)
        lines = content.splitlines()
        total = len(lines)
        if total == 0:
            return Observation(tool="view_file", status="ok", content=f"[{path}: empty file]")

        start = max(1, int(start_line))
        requested_end = max(start, int(end_line))
        end = min(total, requested_end, start + MAX_VIEW_LINES - 1)
        body = _format_numbered_lines(lines, start, end)
        footer = f"\n[Showing {path} lines {start}-{end} of {total}."
        if end < total:
            footer += f" Call view_file(path='{path}', start_line={end + 1}, end_line={min(total, end + 120)}) to read more.]"
        else:
            footer += " End of file.]"
        return Observation(tool="view_file", status="ok", content=body + footer)

    def search_code(query: str, path: str = ".", file_glob: str = "") -> Observation:
        if not query.strip():
            return Observation(tool="search_code", status="error", content="Query must not be empty.")
        total_matches, counts, matches_by_file = runtime.search(
            query, path, file_glob, MAX_SEARCH_MATCHES,
        )

        if total_matches == 0:
            return Observation(
                tool="search_code",
                status="ok",
                content=f"No matches found for '{query}' under '{path}'.",
            )

        if total_matches > MAX_SEARCH_MATCHES:
            summary_lines = [
                f"Found {total_matches} matches across {len(counts)} files (showing per-file counts; refine query or path):"
            ]
            for fpath, count in sorted(counts.items(), key=lambda kv: -kv[1])[:25]:
                summary_lines.append(f"- {fpath} ({count} matches)")
            return Observation(tool="search_code", status="ok", content="\n".join(summary_lines), truncated=True)

        out_lines = [f"Found {total_matches} matches across {len(matches_by_file)} files:"]
        for fpath, hits in matches_by_file.items():
            out_lines.append(f"\n{fpath}:")
            for lineno, snippet in hits:
                out_lines.append(f"  L{lineno:04d} | {snippet}")
        return Observation(tool="search_code", status="ok", content="\n".join(out_lines))

    def edit_file(path: str, old_str: str, new_str: str) -> Observation:
        if not runtime.file_exists(path):
            return Observation(
                tool="edit_file",
                status="error",
                content=f"File not found: '{path}'.",
            )
        if not old_str:
            return Observation(
                tool="edit_file",
                status="error",
                content="old_str must be non-empty and match a unique snippet in the file.",
            )

        original = runtime.read_file(path)
        updated: str | None = None
        changed_start_line = 1

        # Level 1: Exact unique substring match
        exact_count = original.count(old_str)
        if exact_count == 1:
            pos = original.index(old_str)
            changed_start_line = original[:pos].count("\n") + 1
            updated = original.replace(old_str, new_str, 1)
        elif exact_count > 1:
            line_nums = []
            search_from = 0
            while True:
                idx = original.find(old_str, search_from)
                if idx == -1:
                    break
                line_nums.append(original[:idx].count("\n") + 1)
                search_from = idx + 1
            return Observation(
                tool="edit_file",
                status="error",
                content=(
                    f"Edit rejected: old_str matched {exact_count} locations in '{path}' "
                    f"(lines {line_nums}). Include more surrounding lines so the match is unique."
                ),
            )
        else:
            # Level 2: Trailing-whitespace-tolerant line block match
            orig_lines = original.splitlines(keepends=True)
            target_lines = old_str.splitlines()
            hits = _find_whitespace_tolerant_span(orig_lines, target_lines)
            if len(hits) == 1:
                start_idx = hits[0]
                changed_start_line = start_idx + 1
                replacement_lines = new_str.splitlines(keepends=True)
                if new_str and not new_str.endswith("\n") and orig_lines[start_idx + len(target_lines) - 1].endswith("\n"):
                    replacement_lines[-1] += "\n"
                updated = "".join(orig_lines[:start_idx] + replacement_lines + orig_lines[start_idx + len(target_lines):])
            elif len(hits) > 1:
                lines_1b = [h + 1 for h in hits]
                return Observation(
                    tool="edit_file",
                    status="error",
                    content=(
                        f"Edit rejected: whitespace-tolerant match found {len(hits)} locations "
                        f"(lines {lines_1b}). Provide more surrounding lines."
                    ),
                )
            else:
                detail = "Call view_file first and copy the exact lines including indentation."
                if edit_feedback:
                    first = next((line.strip() for line in target_lines if line.strip()), "")
                    candidates = []
                    if first:
                        for number, line in enumerate(orig_lines, 1):
                            ratio = SequenceMatcher(None, first, line.strip()).ratio()
                            if ratio >= 0.65:
                                candidates.append((ratio, number))
                    if candidates:
                        nearest = ", ".join(str(n) for _, n in sorted(candidates, reverse=True)[:3])
                        detail += f" Similar text was found near lines {nearest}."
                return Observation(
                    tool="edit_file", status="error",
                    content=f"Edit failed: old_str not found in '{path}'. {detail}",
                )

        if updated == original:
            return Observation(
                tool="edit_file",
                status="error",
                content=(
                    f"Edit rejected (no-op): new_str leaves '{path}' unchanged. "
                    "Provide an actual code change in new_str before retrying."
                ),
            )
        # Level 3: Poka-Yoke syntax guardrail for Python files
        if path.endswith(".py"):
            try:
                ast.parse(updated, filename=path)
            except SyntaxError as exc:
                return Observation(
                    tool="edit_file",
                    status="error",
                    content=(
                        f"Edit rolled back due to Python SyntaxError in '{path}' at line {exc.lineno}: "
                        f"{exc.msg}. Fix indentation/syntax and retry edit_file."
                    ),
                )

        runtime.write_file(path, updated)
        new_lines = updated.splitlines()
        new_span = max(1, len(new_str.splitlines()))
        ctx_start = max(1, changed_start_line - 5)
        ctx_end = min(len(new_lines), changed_start_line + new_span + 5)
        preview = _format_numbered_lines(new_lines, ctx_start, ctx_end) if new_lines else "[empty file]"
        return Observation(
            tool="edit_file",
            status="ok",
            content=f"Successfully edited '{path}' (AST check passed).\nUpdated context:\n{preview}",
        )

    def run_command(command: str, timeout: int = 60) -> Observation:
        res = runtime.run_command(command, timeout=timeout)
        status = "ok" if res.exit_code == 0 else "error"
        output = res.combined_output or "(no output)"
        header = f"exit_code={res.exit_code} duration_ms={res.duration_ms}"
        if res.timed_out:
            header += " [TIMED OUT]"
        return Observation(
            tool="run_command",
            status=status,
            content=f"{header}\n{output}",
            truncated=res.truncated,
            exit_code=res.exit_code,
        )

    def git_status_diff(include_diff: bool = True) -> Observation:
        st = runtime.run_command("git status -s", timeout=20)
        parts = [f"git status:\n{st.stdout.strip() or '(clean working tree)'}"]
        truncated = False
        if include_diff:
            diff, truncated = truncate_head_tail(runtime.git_diff(), max_chars=6000)
            parts.append(f"\ngit diff:\n{diff.strip() or '(no changes)'}")
        return Observation(tool="git_status_diff", status="ok", content="\n".join(parts), truncated=truncated)

    def finish(summary: str) -> Observation:
        if gate:
            issue = gate.finish_issue()
            if issue:
                return Observation(tool="finish", status="error", content=issue)
        return Observation(
            tool="finish",
            status="ok",
            content=f"Task marked finished. Summary: {summary}",
            metadata={"finished": True, "summary": summary},
        )

    registry.register(ToolSpec(
        name="view_file",
        description="Read a line-numbered window (max 150 lines) of a file in the repository.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path from repo root."},
                "start_line": {"type": "integer", "default": 1},
                "end_line": {"type": "integer", "default": 120},
            },
            "required": ["path"],
        },
        handler=view_file,
    ))
    registry.register(ToolSpec(
        name="search_code",
        description="Search for regex or literal text across repository files with aggregated output.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Regex or literal search pattern."},
                "path": {"type": "string", "default": ".", "description": "Repository file or directory."},
                "file_glob": {"type": "string", "default": ""},
            },
            "required": ["query"],
        },
        handler=search_code,
    ))
    registry.register(ToolSpec(
        name="edit_file",
        description="Replace an exact unique code block (SEARCH/REPLACE) with automatic Python AST syntax validation.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path to modify."},
                "old_str": {"type": "string", "description": "Exact existing snippet (must appear once)."},
                "new_str": {"type": "string", "description": "Replacement snippet."},
            },
            "required": ["path", "old_str", "new_str"],
        },
        handler=edit_file,
    ))
    registry.register(ToolSpec(
        name="run_command",
        description=(
            "Run a stateless shell command (e.g., pytest, python, git) in the repo root. "
            "Run tests in the foreground with an explicit timeout. Do not start tests in the "
            "background or poll for results with sleep. Choose a smaller test subset if needed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
                "timeout": {"type": "integer", "default": 60},
            },
            "required": ["command"],
        },
        handler=run_command,
    ))
    registry.register(ToolSpec(
        name="git_status_diff",
        description="Inspect modified files and current git diff before finishing.",
        parameters={
            "type": "object",
            "properties": {
                "include_diff": {"type": "boolean", "default": True},
            },
        },
        handler=git_status_diff,
    ))
    registry.register(ToolSpec(
        name="finish",
        description="Signal that the issue is fixed and verified by tests.",
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Concise root-cause and verification summary."},
            },
            "required": ["summary"],
        },
        handler=finish,
    ))
    if enable_checkpoints or gate:
        def checkpoint(label: str) -> Observation:
            runtime.checkpoint(label)
            return Observation("checkpoint", "ok", f"Saved checkpoint {label!r}.")

        def rollback(label: str) -> Observation:
            runtime.rollback(label)
            return Observation("rollback", "ok", f"Restored checkpoint {label!r}.")

        params = {
            "type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"],
        }
        registry.register(ToolSpec("checkpoint", "Save the current working tree patch.", params, checkpoint))
        registry.register(ToolSpec(
            "rollback", "Restore a named checkpoint and discard later sandbox edits.", params, rollback,
        ))

    if gate:
        module_hint = ", ".join(sorted(gate.modules)) or "the module used to reproduce the failure"
        registry.register(ToolSpec(
            "run_test",
            f"Reproduce a baseline failure, then verify the current patch. Required modules: {module_hint}.",
            {"type": "object", "properties": {
                "target": {"type": "string"}, "timeout": {"type": "integer", "default": 120},
            }, "required": ["target"]},
            gate.run_test,
        ))

    return registry
