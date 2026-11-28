"""Atomic writes and input fingerprints for resumable benchmark commands."""

import hashlib
import json
import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, encoding="utf-8", mode="w", delete=False,
        ) as out:
            temporary = Path(out.name)
            out.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def input_fingerprint(data: object) -> str:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
