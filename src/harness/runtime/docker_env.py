"""Build an environment for Docker clients without proxying loopback."""

import os
from collections.abc import Mapping


def docker_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if source is None else source)
    entries = ["127.0.0.1", "localhost", "::1"]
    for name in ("NO_PROXY", "no_proxy"):
        entries.extend(part.strip() for part in env.get(name, "").split(",") if part.strip())
    env["NO_PROXY"] = env["no_proxy"] = ",".join(dict.fromkeys(entries))
    return env
