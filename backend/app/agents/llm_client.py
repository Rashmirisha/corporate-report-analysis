"""LLM client for Stage 2 agents + Stage 3 comparator.

Architecture:

    LLMClient (Protocol)
        ├── OllamaLLMClient   ← default, talks to a local Ollama instance
        └── StubLLMClient     ← deterministic, network-free, used by tests

The agents and comparator depend ONLY on the ``LLMClient`` protocol, so a
deployment can swap providers by changing env vars — not by changing code.

Default provider is local Ollama. No cloud / paid API keys are required.

Configuration is read from environment variables (a project-local ``.env`` is
loaded if present). The only required env vars are:

* ``OLLAMA_BASE_URL``   — default ``http://127.0.0.1:11434``
* ``OLLAMA_MODEL``      — default ``qwen2.5:3b`` (chat-tuned, small enough
                          for typical laptops)

Set ``CRA_LLM_STUB=1`` (or pass ``force_stub=True``) to use the deterministic
stub — required by the automated test suite so tests never depend on a
running model.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

import httpx
from dotenv import load_dotenv


# ---------- configuration ----------

# Load .env from the backend folder if present, otherwise from the repo root.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
for candidate in (_BACKEND_ROOT / ".env", _BACKEND_ROOT.parent / ".env"):
    if candidate.exists():
        load_dotenv(candidate, override=False)


@dataclass(frozen=True)
class LLMConfig:
    provider: str            # "ollama" or "stub" — informational
    base_url: str            # e.g. "http://127.0.0.1:11434"
    model: str               # e.g. "qwen2.5:3b"
    timeout_seconds: float = 900.0
    num_predict: int = 1536  # Ollama's "max tokens" knob (covers full AgentAnalysis JSON on CPU; ~5 min on qwen2.5:3b)
    temperature: float = 0.2
    stub: bool = False       # when True, force the deterministic stub

    @classmethod
    def from_env(cls) -> "LLMConfig":
        # Explicit stub flag wins (used by tests).
        stub_raw = os.environ.get("CRA_LLM_STUB", "").strip().lower()
        stub = stub_raw in ("1", "true", "yes", "on")
        return cls(
            provider=os.environ.get("CRA_LLM_PROVIDER", "ollama").strip() or "ollama",
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
                or "http://127.0.0.1:11434",
            model=os.environ.get("OLLAMA_MODEL", "qwen2.5:3b").strip() or "qwen2.5:3b",
            timeout_seconds=float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "900")),
            num_predict=int(os.environ.get("OLLAMA_NUM_PREDICT", "1536")),
            temperature=float(os.environ.get("OLLAMA_TEMPERATURE", "0.2")),
            stub=stub,
        )

    def is_usable(self) -> bool:
        return bool(self.base_url) and bool(self.model)


# ---------- protocol ----------

class LLMClient(Protocol):
    """Anything that can answer a prompt + optional system message with a string."""
    config: LLMConfig

    def complete(self, *, system: str, user: str, json_mode: bool = False) -> str: ...


# ---------- Ollama client ----------

class OllamaLLMClient:
    """Calls Ollama's ``/api/chat`` endpoint.

    Reference: https://github.com/ollama/ollama/blob/main/docs/api.md

    Request shape:
        {
          "model":   "qwen2.5:3b",
          "messages": [{"role":"system","content":"…"},{"role":"user","content":"…"}],
          "stream":  false,
          "format":  {"type":"json_object"}    # only when json_mode=True
          "options": {"temperature": …, "num_predict": …}
        }

    Response shape (non-streaming):
        {"message": {"role":"assistant","content":"…"}, "done": true, …}
    """

    provider_label = "ollama"

    def __init__(self, config: LLMConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._transport = transport
        # Reuse a single HTTP client per process for connection pooling.
        kwargs: dict[str, Any] = {"timeout": httpx.Timeout(config.timeout_seconds)}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        self._client = httpx.Client(**kwargs)

    def complete(self, *, system: str, user: str, json_mode: bool = False) -> str:
        if not self.config.is_usable():
            raise RuntimeError(
                "OllamaLLMClient.complete called without a usable configuration. "
                "Set OLLAMA_BASE_URL and OLLAMA_MODEL, or set CRA_LLM_STUB=1."
            )
        url = self.config.base_url.rstrip("/") + "/api/chat"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.num_predict,
            },
        }
        if json_mode:
            payload["format"] = "json"  # Ollama: free-form "json" requests structured JSON.

        resp = self._client.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Ollama call failed: {resp.status_code} {resp.text[:500]}"
            )
        data = resp.json()
        try:
            return str(data["message"]["content"])
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"unexpected Ollama response shape: {data!r}") from exc

    def is_reachable(self, *, timeout: float = 5.0) -> bool:
        """Quick ``GET /api/tags`` reachability check (used by health probes)."""
        try:
            r = self._client.get(
                self.config.base_url.rstrip("/") + "/api/tags",
                timeout=timeout,
            )
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False


# ---------- deterministic stub (for tests + offline dev) ----------

@dataclass
class StubScript:
    """A single canned response. Tests compose several of these."""
    system_contains: str
    user_contains: str
    response: str
    used: bool = False


class StubLLMClient:
    """Returns deterministic responses matched by simple substring tests.

    No network. No randomness. If no script matches, returns a fallback
    JSON shell that satisfies the agent's expected schema (so tests never
    accidentally trigger real prompts).
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self.config = LLMConfig(**{**self.config.__dict__, "stub": True})
        self._scripts: list[StubScript] = []

    def expect(self, *, system_contains: str = "", user_contains: str = "", response: str = "") -> "StubLLMClient":
        self._scripts.append(
            StubScript(system_contains=system_contains, user_contains=user_contains, response=response)
        )
        return self

    def complete(self, *, system: str, user: str, json_mode: bool = False) -> str:
        for script in self._scripts:
            if (
                (not script.system_contains or script.system_contains in system)
                and (not script.user_contains or script.user_contains in user)
            ):
                script.used = True
                return script.response
        # No match → return a JSON shell so callers that parse JSON don't
        # crash. Tests should always register explicit stubs for the calls
        # they expect.
        return json.dumps(_minimal_agent_shell())

    def unused_scripts(self) -> list[StubScript]:
        return [s for s in self._scripts if not s.used]


def _minimal_agent_shell() -> dict[str, Any]:
    """Minimal agent-output shell matching the Stage 2 schema."""
    return {
        "company": "A",
        "company_overview": {"summary": "", "evidence": []},
        "financial_performance": {"summary": "", "evidence": []},
        "key_financial_metrics": {"summary": "", "evidence": []},
        "operational_information": {"summary": "", "evidence": []},
        "strategic_information": {"summary": "", "evidence": []},
        "business_information": {"summary": "", "evidence": []},
        "strengths": [],
        "weaknesses": [],
        "risks": [],
        "important_observations": [],
        "warnings": ["no LLM script matched — returned empty shell"],
    }


# ---------- factory ----------

def make_default_client(*, force_stub: bool = False) -> LLMClient:
    """Return the right LLMClient for the current environment.

    * If ``force_stub`` is True, or env says ``CRA_LLM_STUB=1``, return a
      :class:`StubLLMClient` — no network.
    * Otherwise return an :class:`OllamaLLMClient` pointed at the configured
      ``OLLAMA_BASE_URL`` / ``OLLAMA_MODEL``.
    """
    cfg = LLMConfig.from_env()
    if force_stub or cfg.stub:
        return StubLLMClient(cfg)
    return OllamaLLMClient(cfg)
