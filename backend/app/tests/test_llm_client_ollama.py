"""Ollama LLM client tests.

These tests:

1. Pin down that ``LLMConfig.from_env`` reads ``OLLAMA_*`` (not
   ``CRA_LLM_*`` cloud API keys).
2. Verify the Ollama client builds a valid ``/api/chat`` request without
   touching the network — using ``httpx.MockTransport``.
3. Verify ``make_default_client`` returns ``OllamaLLMClient`` by default
   and ``StubLLMClient`` when ``CRA_LLM_STUB=1``.
4. Verify ``OllamaLLMClient.is_reachable()`` handles a network outage
   gracefully.

These tests do NOT require a running Ollama instance.
"""
from __future__ import annotations

import json
import os

import httpx
import pytest

from app.agents.llm_client import (
    LLMConfig,
    OllamaLLMClient,
    StubLLMClient,
    make_default_client,
)


# ---------- config ----------

def test_default_config_uses_ollama() -> None:
    cfg = LLMConfig.from_env()
    assert cfg.provider == "ollama"
    assert cfg.base_url.startswith("http")
    assert cfg.model  # non-empty
    assert cfg.stub is False


def test_default_config_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://example.invalid:9999")
    monkeypatch.setenv("OLLAMA_MODEL", "my-test-model")
    monkeypatch.setenv("OLLAMA_TEMPERATURE", "0.5")
    monkeypatch.setenv("OLLAMA_NUM_PREDICT", "256")
    cfg = LLMConfig.from_env()
    assert cfg.base_url == "http://example.invalid:9999"
    assert cfg.model == "my-test-model"
    assert cfg.temperature == 0.5
    assert cfg.num_predict == 256


def test_stub_flag_short_circuits(monkeypatch) -> None:
    monkeypatch.setenv("CRA_LLM_STUB", "1")
    cfg = LLMConfig.from_env()
    assert cfg.stub is True


def test_no_paid_api_env_vars_required(monkeypatch) -> None:
    """CRA_LLM_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY must NOT be read."""
    monkeypatch.delenv("CRA_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    cfg = LLMConfig.from_env()
    assert cfg.is_usable()


# ---------- request shape (no network) ----------

def _ok_ollama_response(content: str = '{"hello":"world"}') -> dict:
    return {"message": {"role": "assistant", "content": content}, "done": True}


def test_ollama_client_builds_correct_chat_request() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_ollama_response('{"ok":1}'))

    transport = httpx.MockTransport(handler)
    cfg = LLMConfig(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen2.5:3b",
        timeout_seconds=5.0,
    )
    client = OllamaLLMClient(cfg, transport=transport)
    out = client.complete(system="sys-x", user="usr-y", json_mode=True)

    assert captured["method"] == "POST"
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    body = captured["body"]
    assert body["model"] == "qwen2.5:3b"
    assert body["stream"] is False
    assert body["format"] == "json"  # json_mode is on
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == "sys-x"
    assert body["messages"][1]["role"] == "user"
    assert body["messages"][1]["content"] == "usr-y"
    assert body["options"]["temperature"] == cfg.temperature
    assert body["options"]["num_predict"] == cfg.num_predict
    assert out == '{"ok":1}'


def test_ollama_client_json_mode_off_omits_format() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_ollama_response("ok"))

    transport = httpx.MockTransport(handler)
    cfg = LLMConfig(provider="ollama", base_url="http://127.0.0.1:11434", model="qwen2.5:3b")
    client = OllamaLLMClient(cfg, transport=transport)
    client.complete(system="s", user="u", json_mode=False)
    assert "format" not in captured["body"]


def test_ollama_client_propagates_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="model loading")

    transport = httpx.MockTransport(handler)
    cfg = LLMConfig(provider="ollama", base_url="http://127.0.0.1:11434", model="qwen2.5:3b")
    client = OllamaLLMClient(cfg, transport=transport)
    with pytest.raises(RuntimeError, match="503"):
        client.complete(system="s", user="u")


def test_ollama_client_handles_unexpected_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not": "ollama"})

    transport = httpx.MockTransport(handler)
    cfg = LLMConfig(provider="ollama", base_url="http://127.0.0.1:11434", model="qwen2.5:3b")
    client = OllamaLLMClient(cfg, transport=transport)
    with pytest.raises(RuntimeError, match="unexpected Ollama response"):
        client.complete(system="s", user="u")


def test_ollama_is_reachable_true() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    transport = httpx.MockTransport(handler)
    cfg = LLMConfig(provider="ollama", base_url="http://127.0.0.1:11434", model="x")
    client = OllamaLLMClient(cfg, transport=transport)
    assert client.is_reachable() is True


def test_ollama_is_reachable_false_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    transport = httpx.MockTransport(handler)
    cfg = LLMConfig(provider="ollama", base_url="http://127.0.0.1:11434", model="x")
    client = OllamaLLMClient(cfg, transport=transport)
    assert client.is_reachable() is False


# ---------- factory ----------

def test_factory_returns_ollama_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CRA_LLM_STUB", raising=False)
    c = make_default_client()
    assert isinstance(c, OllamaLLMClient)


def test_factory_returns_stub_when_forced(monkeypatch) -> None:
    monkeypatch.delenv("CRA_LLM_STUB", raising=False)
    c = make_default_client(force_stub=True)
    assert isinstance(c, StubLLMClient)


def test_factory_returns_stub_when_env_says_so(monkeypatch) -> None:
    monkeypatch.setenv("CRA_LLM_STUB", "1")
    c = make_default_client()
    assert isinstance(c, StubLLMClient)


def test_factory_does_not_use_paid_cloud_keys(monkeypatch) -> None:
    """If somehow CRA_LLM_API_KEY is set, the factory must not try to use it
    as if it were an OpenAI-compatible bearer token — it must still return
    an Ollama client pointed at OLLAMA_BASE_URL.
    """
    monkeypatch.setenv("CRA_LLM_API_KEY", "leaked-or-stale-key")
    monkeypatch.delenv("CRA_LLM_STUB", raising=False)
    c = make_default_client()
    assert isinstance(c, OllamaLLMClient)
    assert c.config.base_url.startswith("http")
