"""CLI entry point for coding-agent-harness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness.agent.controller import AgentController
from harness.config import HarnessConfig
from harness.events.stream import EventStream, JsonlTrajectoryLogger
from harness.llm.client import OpenAICompatibleClient
from harness.repomap.mapper import RepoMapper
from harness.runtime.local import LocalWorkspaceRuntime
from harness.tools.aci import build_default_tool_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coding-harness", description="Repo-level Coding Agent Harness CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_map = sub.add_parser("repomap", help="Generate an AST repository skeleton map")
    p_map.add_argument("--repo", type=Path, default=Path("."), help="Path to local repository")
    p_map.add_argument("--max-tokens", type=int, default=1500)

    p_solve = sub.add_parser("solve", help="Run the agent against a local repository and task prompt")
    p_solve.add_argument("--repo", type=Path, required=True, help="Path to target Git repository")
    p_solve.add_argument("--task", type=str, required=True, help="Issue description or CI failure prompt")
    p_solve.add_argument("--instance-id", type=str, default="local")
    p_solve.add_argument("--with-repomap", action="store_true", help="Attach AST repo map to initial prompt")

    args = parser.parse_args(argv)

    if args.command == "repomap":
        with LocalWorkspaceRuntime(args.repo) as rt:
            print(RepoMapper(rt).build_map(max_tokens=args.max_tokens))
        return 0

    if args.command == "solve":
        cfg = HarnessConfig.from_env()
        if not cfg.llm.api_key:
            print("Error: LLM_API_KEY is not set. Copy .env.example and export LLM_API_KEY first.", file=sys.stderr)
            return 2
        with LocalWorkspaceRuntime(args.repo, config=cfg.sandbox) as rt:
            stream = EventStream()
            traj_path = cfg.trajectories_dir / f"{args.instance_id}.jsonl"
            stream.subscribe(JsonlTrajectoryLogger(traj_path))
            tools = build_default_tool_registry(rt)
            llm = OpenAICompatibleClient(cfg.llm)
            repo_map = RepoMapper(rt).build_map(max_tokens=cfg.context.repo_map_max_tokens) if args.with_repomap else ""
            controller = AgentController(llm=llm, runtime=rt, tools=tools, event_stream=stream, config=cfg)
            result = controller.run(task_prompt=args.task, instance_id=args.instance_id, repo_map=repo_map)
            print(f"[{result.status}] steps={result.steps} cost=${result.total_cost_usd:.4f} trajectory={traj_path}")
            print(result.summary)
            if result.patch:
                print("\n--- Generated Git Diff ---\n" + result.patch)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
