"""Text search shared by the local and Docker runtimes.

The CLI in this module also runs inside historical SWE-bench Python environments.
"""

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

IGNORED_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}


def workspace_files(root, base):
    if base.is_file():
        yield base.relative_to(root).as_posix()
        return
    for directory, subdirs, names in os.walk(base):
        subdirs[:] = sorted(d for d in subdirs if d not in IGNORED_DIRS)
        for name in sorted(names):
            yield (Path(directory) / name).relative_to(root).as_posix()


def search_files(query, file_glob, paths, read_file, max_matches):
    try:
        pattern = re.compile(query)
    except re.error:
        pattern = re.compile(re.escape(query))

    counts = {}
    excerpts = {}
    total = 0
    for path in paths:
        if file_glob and not (
            fnmatch.fnmatch(path, file_glob) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], file_glob)
        ):
            continue
        try:
            text = read_file(path)
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                counts[path] = counts.get(path, 0) + 1
                total += 1
                if total <= max_matches:
                    excerpts.setdefault(path, []).append((number, line.strip()[:160]))
    return total, counts, excerpts


if __name__ == "__main__":
    root = Path.cwd()
    query, rel_dir, file_glob, max_matches = sys.argv[1:]
    base = (root / rel_dir).resolve()
    base.relative_to(root)

    def read_workspace_file(rel_path):
        path = (root / rel_path).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise PermissionError(rel_path)
        return path.read_text(encoding="utf-8")

    print(json.dumps(search_files(
        query, file_glob, workspace_files(root, base), read_workspace_file, int(max_matches),
    )))
