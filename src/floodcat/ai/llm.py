"""Which language model serves the AI features.

FLOODCAT_AI_PROVIDER = gemini | ollama. When unset: Gemini if GEMINI_API_KEY (or GOOGLE_API_KEY) is set, otherwise
Ollama if OLLAMA_MODEL is set, otherwise AI is off and the rest of the app works without it.
"""

import os
from ..core.errors import ModelError

PROVIDERS = ("gemini", "ollama")


def provider():
    chosen = os.getenv("FLOODCAT_AI_PROVIDER", "").strip().lower()
    if chosen:
        if chosen not in PROVIDERS:
            raise ModelError(
                "ai_unavailable",
                f"FLOODCAT_AI_PROVIDER must be one of {', '.join(PROVIDERS)}",
            )
        return chosen
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    if os.getenv("OLLAMA_MODEL"):
        return "ollama"
    return None


def configured(name):
    """Whether this provider has what it needs on this server (key or model name), regardless of the default."""
    if name == "gemini":
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return name == "ollama" and bool(os.getenv("OLLAMA_MODEL"))


def available():
    try:
        chosen = provider()
    except ModelError:
        return False
    if chosen == "gemini":
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return chosen == "ollama" and bool(os.getenv("OLLAMA_MODEL"))


def make_client(chosen=None):
    """A client for `chosen` ('gemini' / 'ollama'), or for the server default when None."""
    if chosen is not None and chosen not in PROVIDERS:
        raise ModelError("ai_unavailable", f"Unknown AI provider {chosen}")
    if chosen is not None and not configured(chosen):
        raise ModelError(
            "ai_unavailable",
            "Gemini is not configured on this server (GEMINI_API_KEY)" if chosen == "gemini"
            else "Ollama is not configured on this server (OLLAMA_MODEL)",
        )
    chosen = chosen or provider()
    if chosen == "ollama":
        from .ollama import OllamaClient

        return OllamaClient()
    if chosen == "gemini":
        from .gemini import GeminiClient

        return GeminiClient()
    raise ModelError(
        "ai_unavailable",
        "AI is off: set GEMINI_API_KEY, or OLLAMA_MODEL for a local Ollama model",
    )


def describe():
    """Short label for the interface, e.g. 'Ollama llama3.2:3b (local)'."""
    chosen = provider() if available() else None
    if chosen == "ollama":
        return f"Ollama {os.getenv('OLLAMA_MODEL')} (local)"
    if chosen == "gemini":
        return "Google Gemini"
    return "not configured"
