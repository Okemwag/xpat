"""Gemini boundary. Every response is untrusted data and is re-validated by deterministic code.

Models are tried in order (GEMINI_MODEL, then GEMINI_FALLBACK_MODELS). Temporary failures
(rate limits, overload) are retried with backoff; a retired or overloaded model falls through
to the next one. The model that actually answered is recorded in `last_model` for provenance.
"""

import json
import os
import time
from ..core.errors import ModelError

DEFAULT_MODELS = ("gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-latest")
RETRYABLE = {429, 500, 502, 503, 504}
NEXT_MODEL = {404} | RETRYABLE
ATTEMPTS_PER_MODEL = 2
BACKOFF_S = 1.5


def model_chain():
    primary = [os.getenv("GEMINI_MODEL")] if os.getenv("GEMINI_MODEL") else []
    fallback = [
        m.strip()
        for m in os.getenv("GEMINI_FALLBACK_MODELS", ",".join(DEFAULT_MODELS)).split(
            ","
        )
        if m.strip()
    ]
    return list(dict.fromkeys(primary + fallback))


class GeminiClient:
    def __init__(self, api_key=None, model=None, timeout_s=60, sleep=time.sleep):
        self.api_key = (
            api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        )
        self.models = [model] if model else model_chain()
        self.model = self.models[0]
        self.last_model = None
        self._sleep = sleep
        if not self.api_key:
            raise ModelError(
                "ai_unavailable", "Set GEMINI_API_KEY to enable AI features"
            )
        try:
            from google import genai
        except ImportError:
            raise ModelError(
                "ai_unavailable",
                "Install the 'ai' extra (google-genai) to enable AI features",
            ) from None
        self._client = genai.Client(
            api_key=self.api_key, http_options={"timeout": timeout_s * 1000}
        )

    def _call(self, model, system, prompt, schema):
        from google.genai import types

        response = self._client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        return response.text

    def generate_json(self, system, prompt, schema):
        from google.genai import errors

        failures = []
        for model in self.models:
            for attempt in range(ATTEMPTS_PER_MODEL):
                try:
                    text = self._call(model, system, prompt, schema)
                except errors.APIError as exc:
                    code = getattr(exc, "code", None)
                    message = " ".join(str(getattr(exc, "message", "") or exc).split())[
                        :200
                    ]
                    failures.append(f"{model}: {code} {message}")
                    if code in RETRYABLE and attempt + 1 < ATTEMPTS_PER_MODEL:
                        self._sleep(BACKOFF_S * (attempt + 1))
                        continue
                    if code in NEXT_MODEL:
                        break
                    raise ModelError(
                        "ai_failed",
                        f"Gemini request failed — {failures[-1]}. Nothing was changed.",
                    ) from None
                except Exception as exc:
                    raise ModelError(
                        "ai_failed",
                        f"Gemini request failed ({type(exc).__name__}). Nothing was changed.",
                    ) from None
                if not text:
                    raise ModelError(
                        "ai_failed",
                        f"{model} returned no content (possibly blocked). Nothing was changed.",
                    )
                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    raise ModelError(
                        "ai_failed",
                        f"{model} returned malformed JSON. Nothing was changed.",
                    ) from None
                self.last_model = model
                return result
        raise ModelError(
            "ai_failed",
            "No Gemini model is available right now — "
            + " | ".join(failures[-3:])
            + ". Nothing was changed; try again shortly.",
        )


def available():
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def model_used(llm):
    return getattr(llm, "last_model", None) or getattr(llm, "model", "llm")
