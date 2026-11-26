from __future__ import annotations

import json
import os
import unittest
from io import BytesIO
from unittest.mock import patch

from harness.config import LLMConfig
from harness.llm.client import OpenAICompatibleClient

GATEWAY_RESPONSE = {
    "choices": [{
        "finish_reason": "tool_calls",
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_example",
                "type": "function",
                "function": {"name": "view_file", "arguments": '{"path": "calc.py"}'},
            }],
        },
    }],
    "usage": {"prompt_tokens": 10_000, "completion_tokens": 1_000},
}


class TestOpenAICompatibleClient(unittest.TestCase):
    def test_deepseek_tool_call_and_cache_pricing(self):
        config = LLMConfig(
            base_url="https://api.deepseek.com", model="deepseek-flash", thinking="disabled",
            input_cost_per_1m_usd=0.30, cached_input_cost_per_1m_usd=0.006,
            output_cost_per_1m_usd=1.20,
        )
        reply = {
            **GATEWAY_RESPONSE,
            "usage": {**GATEWAY_RESPONSE["usage"], "prompt_cache_hit_tokens": 8_000},
        }
        tools = [{"type": "function", "function": {"name": "view_file"}}]
        with patch("urllib.request.urlopen", return_value=BytesIO(json.dumps(reply).encode())) as send:
            result = OpenAICompatibleClient(config).chat([{"role": "user", "content": "Read calc"}], tools)
        request = send.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["tools"], tools)
        self.assertEqual(result.tool_calls[0].call_id, "call_example")
        self.assertEqual(result.tool_calls[0].name, "view_file")
        self.assertEqual(result.tool_calls[0].arguments, {"path": "calc.py"})
        self.assertEqual(result.usage.prompt_tokens, 10_000)
        self.assertEqual(result.usage.cached_tokens, 8_000)
        self.assertEqual(result.usage.completion_tokens, 1_000)
        self.assertAlmostEqual(result.usage.cost_usd, 0.001848)

    def test_openai_style_cached_tokens_and_explicit_zero(self):
        client = OpenAICompatibleClient(LLMConfig())
        reply = {
            **GATEWAY_RESPONSE,
            "usage": {**GATEWAY_RESPONSE["usage"], "prompt_tokens_details": {"cached_tokens": 900}},
        }
        result = client._parse_response(reply, 1)
        self.assertEqual(result.usage.cached_tokens, 900)
        reply["usage"]["prompt_cache_hit_tokens"] = 0
        self.assertEqual(client._parse_response(reply, 1).usage.cached_tokens, 0)

    def test_env_configuration_uses_dataclass_defaults(self):
        env = {"LLM_INPUT_COST_PER_1M_USD": "0.30", "LLM_MAX_TOKENS": "1024"}
        with patch.dict(os.environ, env, clear=True):
            config = LLMConfig.from_env()
        self.assertEqual(config.base_url, LLMConfig().base_url)
        self.assertEqual(config.timeout_seconds, LLMConfig().timeout_seconds)
        self.assertEqual(config.input_cost_per_1m_usd, 0.30)
        self.assertEqual(config.max_tokens, 1024)
