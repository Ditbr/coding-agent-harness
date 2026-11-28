from __future__ import annotations

import json
import os
import unittest
import urllib.error
from email.message import Message
from http.client import RemoteDisconnected
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

    def test_429_respects_retry_after_and_recovers(self):
        hdrs = Message()
        hdrs["Retry-After"] = "7"
        err_429 = urllib.error.HTTPError(
            "https://api.example.com/v1/chat/completions", 429, "Too Many Requests", hdrs, None,
        )
        ok_resp = BytesIO(json.dumps(GATEWAY_RESPONSE).encode())
        client = OpenAICompatibleClient(LLMConfig(max_retries=2), rpm_limit=0)
        with (
            patch("urllib.request.urlopen", side_effect=[err_429, err_429, err_429, ok_resp]) as send,
            patch("harness.llm.client.time.sleep") as sleeper,
        ):
            res = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(send.call_count, 4)
        self.assertEqual(res.tool_calls[0].name, "view_file")
        self.assertTrue(all(call.args[0] >= 7.0 for call in sleeper.call_args_list))

    def test_auto_detects_rpm_limit_from_gateway_headers(self):
        client = OpenAICompatibleClient(LLMConfig(), rpm_limit=0)
        client._note_response_rate_limit({"x-ratelimit-api_key-limit-requests": "20"})
        self.assertEqual(client._rpm_limit, 18)

    def test_retry_remote_disconnect(self):
        response = BytesIO(json.dumps(GATEWAY_RESPONSE).encode())
        with (
            patch("urllib.request.urlopen", side_effect=[RemoteDisconnected("dropped"), response]) as send,
            patch("time.sleep"),
        ):
            result = OpenAICompatibleClient(LLMConfig(max_retries=2)).chat([])
        self.assertEqual(send.call_count, 2)
        self.assertEqual(result.tool_calls[0].name, "view_file")
