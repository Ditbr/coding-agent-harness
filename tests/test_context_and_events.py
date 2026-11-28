"""Unit tests for EventStream, JSONL trajectory logger, ContextManager, and Eval summary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness.config import ContextConfig
from harness.context.manager import ContextManager
from harness.eval.models import EvalResult, FailureCategory, Prediction
from harness.eval.runner import summarize_results, write_predictions_jsonl
from harness.events.schema import Event, EventType, Observation, TokenUsage
from harness.events.stream import EventStream, JsonlTrajectoryLogger


class TestContextAndEvents(unittest.TestCase):
    def test_event_stream_and_jsonl_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "traj.jsonl"
            stream = EventStream()
            stream.subscribe(JsonlTrajectoryLogger(log_path))

            stream.publish(Event(
                run_id="v0.1",
                instance_id="demo__1",
                step=1,
                event_type=EventType.ACTION,
                payload={"tool": "view_file"},
                usage=TokenUsage(prompt_tokens=1000, cached_tokens=800, completion_tokens=50, cost_usd=0.001),
            ))
            records = JsonlTrajectoryLogger.load(log_path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["event_type"], "action")
            self.assertEqual(records[0]["usage"]["cached_tokens"], 800)

    def test_observation_masking_preserves_recent_and_prefix(self) -> None:
        ctx = ContextManager(config=ContextConfig(keep_recent_observations=2, mask_threshold_chars=50))
        ctx.add_user_message("Fix bug")
        for i in range(4):
            ctx.add_observation(Observation(
                tool="view_file",
                call_id=f"c{i}",
                status="ok",
                content=f"step-{i} " + ("A" * 120),
            ))

        msgs = ctx.build_messages()
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 4)
        # First 2 bulky observations masked; last 2 kept intact
        self.assertIn("[Observation masked:", tool_msgs[0]["content"])
        self.assertIn("[Observation masked:", tool_msgs[1]["content"])
        self.assertNotIn("[Observation masked:", tool_msgs[2]["content"])
        self.assertNotIn("[Observation masked:", tool_msgs[3]["content"])
        # System prompt stays unchanged at index 0 for Prompt Caching stability
        self.assertEqual(msgs[0]["role"], "system")

    def test_edit_observations_never_masked_and_raw_message_sanitized(self) -> None:
        from harness.llm.client import LLMResponse

        ctx = ContextManager(config=ContextConfig(keep_recent_observations=1, mask_threshold_chars=20))
        ctx.add_user_message("Fix bug")
        ctx.add_assistant_response(LLMResponse(
            content="",
            raw_message={
                "role": "assistant",
                "content": None,
                "reasoning_content": "thinking step",
                "provider_specific_fields": {"internal": 1},
                "annotations": [],
            },
        ))
        ctx.add_observation(Observation(tool="edit_file", call_id="e1", status="ok", content="Edited " + ("X" * 80)))
        ctx.add_observation(Observation(tool="view_file", call_id="v1", status="ok", content="Viewed " + ("Y" * 80)))
        ctx.add_observation(Observation(tool="view_file", call_id="v2", status="ok", content="Latest " + ("Z" * 80)))

        msgs = ctx.build_messages()
        assistant_msg = next(m for m in msgs if m["role"] == "assistant")
        self.assertEqual(assistant_msg["reasoning_content"], "thinking step")
        self.assertNotIn("provider_specific_fields", assistant_msg)
        self.assertNotIn("annotations", assistant_msg)
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        # edit_file is old and bulky, yet must remain unmasked; old view_file is masked
        self.assertNotIn("[Observation masked:", tool_msgs[0]["content"])
        self.assertIn("[Observation masked:", tool_msgs[1]["content"])
        self.assertNotIn("[Observation masked:", tool_msgs[2]["content"])

    def test_eval_predictions_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pred_path = write_predictions_jsonl(
                [Prediction("repo__1", "v0.1", "diff --git a/x.py b/x.py\n")],
                Path(tmp) / "preds.jsonl",
            )
            self.assertTrue(pred_path.exists())

        summary = summarize_results("v0.1", [
            EvalResult("r1", True, steps=8, cost_usd=0.04, prompt_tokens=10000, cached_tokens=7000),
            EvalResult("r2", False, steps=20, cost_usd=0.10, prompt_tokens=10000, cached_tokens=5000,
                       failure_category=FailureCategory.E1_LOC_MISS),
        ])
        self.assertAlmostEqual(summary.pass_at_1, 0.5)
        self.assertAlmostEqual(summary.cache_hit_rate, 0.6)
        self.assertEqual(summary.failure_breakdown["E1_LOC_MISS"], 1)


if __name__ == "__main__":
    unittest.main()
