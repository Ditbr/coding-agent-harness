"""Pull all SWE-bench images for a frozen dataset onto the active Docker context (local or remote)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from harness.eval.runner import read_jsonl

ROOT = Path(__file__).resolve().parents[1]


def docker_cmd(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], text=True, capture_output=True, check=check)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/swebench_verified_30.jsonl")
    parser.add_argument("--platform", type=str, default="linux/amd64")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--manifest-out", type=Path, help="Optional JSON path to record pulled image digests")
    args = parser.parse_args()

    info = docker_cmd("info", "--format", "{{.Name}} | {{.Architecture}} | {{.OperatingSystem}}")
    ctx = docker_cmd("context", "show").stdout.strip()
    print(f"Active Docker context: {ctx} ({info.stdout.strip()})", flush=True)

    rows = read_jsonl(args.dataset)
    images = [(row["instance_id"], row["image"]) for row in rows]
    manifest: dict[str, dict[str, str]] = {}
    failed: list[str] = []

    for idx, (instance_id, image) in enumerate(images, start=1):
        inspect = docker_cmd("image", "inspect", image, check=False)
        if inspect.returncode == 0:
            print(f"[{idx}/{len(images)}] cached  {instance_id} -> {image}", flush=True)
        else:
            print(f"[{idx}/{len(images)}] pulling {instance_id} -> {image}", flush=True)
            ok = False
            for attempt in range(1, args.retries + 1):
                proc = subprocess.run(
                    ["docker", "pull", "--platform", args.platform, image],
                    check=False,
                )
                if proc.returncode == 0:
                    ok = True
                    break
                print(f"  retry {attempt}/{args.retries} failed for {image}", file=sys.stderr, flush=True)
                time.sleep(min(3 * attempt, 10))
            if not ok:
                failed.append(instance_id)
                continue

        meta_proc = docker_cmd(
            "image", "inspect", image,
            "--format", "{{.Id}}|{{.Architecture}}|{{index .RepoDigests 0}}",
            check=False,
        )
        if meta_proc.returncode == 0:
            img_id, arch, digest = (meta_proc.stdout.strip().split("|") + ["", "", ""])[:3]
            manifest[instance_id] = {
                "tag": image,
                "digest": digest,
                "id": img_id,
                "platform": f"linux/{arch}",
            }

    if args.manifest_out:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Manifest written to {args.manifest_out}", flush=True)

    df = docker_cmd("system", "df", check=False)
    if df.returncode == 0:
        print("\n" + df.stdout.strip(), flush=True)

    if failed:
        print(f"Failed instances ({len(failed)}): {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"All {len(images)} images ready on context '{ctx}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
