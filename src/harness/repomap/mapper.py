"""Lightweight Python AST RepoMapper (V0.1 baseline before Week 4 Tree-sitter + PageRank)."""

from __future__ import annotations

import ast

from harness.runtime.base import SandboxRuntime


class RepoMapper:
    """Extracts a compact class/function signature skeleton under a rough token budget."""

    def __init__(self, runtime: SandboxRuntime) -> None:
        self.runtime = runtime

    def build_map(self, focus_files: list[str] | None = None, max_tokens: int = 1500) -> str:
        focus = set(focus_files or [])
        py_files = [f for f in self.runtime.list_files(".") if f.endswith(".py")]
        # Prioritize focus files first, then shorter/shallower module paths
        py_files.sort(key=lambda f: (0 if f in focus else 1, f.count("/"), f))

        max_chars = max_tokens * 4
        sections: list[str] = []
        used_chars = 0

        for rel_path in py_files:
            skeleton = self._extract_python_skeleton(rel_path)
            if not skeleton:
                continue
            block = f"{rel_path}:\n{skeleton}\n"
            if used_chars + len(block) > max_chars:
                break
            sections.append(block)
            used_chars += len(block)

        if not sections:
            return "(No Python symbols indexed in repository.)"
        return "\n".join(sections).strip()

    def _extract_python_skeleton(self, rel_path: str) -> str:
        try:
            source = self.runtime.read_file(rel_path)
            tree = ast.parse(source, filename=rel_path)
        except (OSError, UnicodeDecodeError, SyntaxError):
            return ""

        lines: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                lines.append(f"│ class {node.name}:")
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = ast.unparse(item.args) if hasattr(ast, "unparse") else "..."
                        prefix = "async def" if isinstance(item, ast.AsyncFunctionDef) else "def"
                        lines.append(f"│     {prefix} {item.name}({args})")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                lines.append(f"│ {prefix} {node.name}({args})")
        return "\n".join(lines)
