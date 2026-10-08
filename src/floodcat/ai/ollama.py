"""Ollama boundary: a locally hosted model (e.g. `ollama pull llama3.2:3b`) behind the same interface as the Gemini client.

Structured output uses Ollama's `format` field with the same JSON schema the Gemini client sends. Every response is
untrusted data and is re-validated by the same deterministic code as Gemini output. Text stays on the Ollama host.
"""

import json
import os
from ..core.errors import ModelError

DEFAULT_HOST = "http://127.0.0.1:11434"


class OllamaClient:
    def __init__(
        self, model=None, host=None, timeout_s=None, num_ctx=None, transport=None
    ):
        self.model = model or os.getenv("OLLAMA_MODEL")
        if not self.model:
            raise ModelError(
                "ai_unavailable",
                "Set OLLAMA_MODEL (e.g. llama3.2:3b) to use a local Ollama model",
            )
        self.host = (host or os.getenv("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        if not self.host.startswith(("http://", "https://")):
            self.host = "http://" + self.host
        self.timeout_s = float(timeout_s or os.getenv("OLLAMA_TIMEOUT_S", 300))
        # Ollama's default context window is small; documents and fact packs need more or they are silently cut.
        self.num_ctx = int(num_ctx or os.getenv("OLLAMA_NUM_CTX", 8192))
        self.last_model = None
        self._transport = transport

    def generate_json(self, system, prompt, schema):
        import httpx

        body = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_ctx": self.num_ctx},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            with httpx.Client(
                timeout=self.timeout_s, transport=self._transport
            ) as client:
                response = client.post(f"{self.host}/api/chat", json=body)
        except httpx.TimeoutException:
            raise ModelError(
                "ai_failed",
                f"Ollama ({self.model}) took longer than {self.timeout_s:g} s. Nothing was changed; "
                "try a shorter input or raise OLLAMA_TIMEOUT_S.",
            ) from None
        except httpx.HTTPError:
            raise ModelError(
                "ai_unavailable",
                f"Ollama is not reachable at {self.host}. Start it (`ollama serve`) and try again. Nothing was changed.",
            ) from None
        if response.status_code == 404:
            raise ModelError(
                "ai_unavailable",
                f'Ollama has no model "{self.model}". Run `ollama pull {self.model}` or set OLLAMA_MODEL. Nothing was changed.',
            )
        if response.status_code >= 400:
            detail = " ".join(str(response.text).split())[:200]
            raise ModelError(
                "ai_failed",
                f"Ollama request failed — {response.status_code} {detail}. Nothing was changed.",
            )
        try:
            text = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise ModelError(
                "ai_failed",
                "Ollama returned an unexpected response. Nothing was changed.",
            ) from None
        if not text or not text.strip():
            raise ModelError(
                "ai_failed", f"{self.model} returned no content. Nothing was changed."
            )
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            raise ModelError(
                "ai_failed",
                f"{self.model} returned malformed JSON. Nothing was changed.",
            ) from None
        self.last_model = f"ollama:{self.model}"
        return result
