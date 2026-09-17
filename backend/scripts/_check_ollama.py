"""One-shot reachability + 1-token round-trip test."""
from app.agents.llm_client import OllamaLLMClient, LLMConfig
import time

c = OllamaLLMClient(LLMConfig.from_env())
print("reachable:", c.is_reachable())
t = time.time()
r = c.complete(
    system='You are a JSON-only assistant. Reply with valid JSON only.',
    user='Return JSON: {"ping": "pong"}',
    json_mode=True,
)
print(f"round-trip: {time.time() - t:.2f}s")
print("raw:", repr(r[:200]))
