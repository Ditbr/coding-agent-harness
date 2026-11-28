"""Lightweight Python AST RepoMapper (V0.1 baseline before Week 4 Tree-sitter + PageRank)."""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict

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

    def build_ranked_map(
        self, query: str = "", focus_files: list[str] | None = None, max_tokens: int = 1500,
    ) -> str:
        try:
            import networkx as nx
            import tree_sitter_python
            from tree_sitter import Language, Parser
        except ImportError as exc:
            raise RuntimeError("Install the repomap extra to use --with-repomap") from exc

        parser = Parser(Language(tree_sitter_python.language()))
        definitions: dict[str, list[tuple[str, str]]] = {}
        references: dict[str, Counter[str]] = {}
        owners: dict[str, set[str]] = defaultdict(set)
        graph = nx.DiGraph()
        for path, source in self.runtime.python_sources():
            root = parser.parse(source.encode("utf-8")).root_node
            symbols, names = self._index_python(root)
            graph.add_node(path)
            definitions[path], references[path] = symbols, names
            for name, _ in symbols:
                owners[name].add(path)

        if not definitions:
            return "(No Python symbols indexed in repository.)"
        for source, names in references.items():
            weights: Counter[str] = Counter()
            for name, count in names.items():
                targets = owners.get(name, set()) - {source}
                if 0 < len(targets) <= 8:
                    for target in targets:
                        weights[target] += min(count, 4) / len(targets)
            for target, weight in weights.items():
                graph.add_edge(source, target, weight=weight)

        words = {word.lower() for word in re.findall(r"[A-Za-z_]\w+", query)}
        focus = set(focus_files or [])
        prior = {}
        for path, symbols in definitions.items():
            identifiers = {item.lower() for item in re.findall(r"[A-Za-z_]\w+", path)}
            identifiers.update(name.lower() for name, _ in symbols)
            prior[path] = 1 + 12 * len(words & identifiers) + 30 * (path in focus)
        scores = nx.pagerank(graph, personalization=prior, weight="weight", max_iter=200)
        ranked = sorted(definitions, key=lambda path: (path not in focus, -scores[path], path))

        remaining = max_tokens * 4
        blocks: list[str] = []
        for path in ranked:
            header = f"{path}:"
            block = [header]
            section_cap = min(remaining, max(240, max_tokens * 4 // 4))
            budget = section_cap - len(header) - 1
            prioritized = sorted(definitions[path], key=lambda symbol: symbol[0].lower() not in words)
            for _, signature in prioritized:
                if len(signature) + 1 <= budget:
                    block.append(signature)
                    budget -= len(signature) + 1
            if len(block) > 1:
                blocks.append("\n".join(block))
                remaining -= section_cap - budget
        return "\n".join(blocks) or "(No Python symbols fit the repository map budget.)"

    @staticmethod
    def _index_python(root) -> tuple[list[tuple[str, str]], Counter[str]]:
        symbols = []
        references: Counter[str] = Counter()
        stack = [(root, ())]
        while stack:
            node, scopes = stack.pop()
            if node.type in {"class_definition", "function_definition"}:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = name_node.text.decode("utf-8")
                    if len(scopes) < 2:
                        params = node.child_by_field_name("parameters")
                        args = " ".join(params.text.decode("utf-8").split()) if params else ""
                        kind = "class" if node.type == "class_definition" else "def"
                        symbols.append((name, f"{node.start_point.row + 1}: {kind} {'.'.join((*scopes, name))}{args}"))
                    scopes = (*scopes, name)
                    stack.extend((child, scopes) for child in reversed(node.named_children) if child != name_node)
                    continue
            if node.type == "identifier":
                references[node.text.decode("utf-8")] += 1
            else:
                stack.extend((child, scopes) for child in reversed(node.named_children))
        return symbols, references

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
