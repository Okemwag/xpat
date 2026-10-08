"""Which language model serves an AI request: Google Gemini (cloud) or a local Ollama model such as Llama (this server).

What is configured on the server:
- Gemini when GEMINI_API_KEY (or GOOGLE_API_KEY) is set; Ollama when OLLAMA_MODEL is set. Either, both or neither.
- FLOODCAT_AI_PROVIDER = gemini | ollama is the server's default when both are configured.

What is used for a request (``choose``), in order:
1. The organisation's allowed providers (``ai_providers`` setting) that are configured on this server.
2. If the request carries client data (documents, schedules, descriptions, results on real exposure) and the organisation set
   ``ai_local_for_client_data``, only the local model is allowed. If it is not configured, the request is refused; it never
   falls back to the cloud.
3. The user's own preference, then the organisation's default, then the server default, then the first allowed provider.
"""

import os
from ..core.errors import ModelError

PROVIDERS = ("gemini", "ollama")
LABEL = {"gemini": "Google Gemini (cloud)", "ollama": "Local model on this server"}


def _env_provider():
    chosen = os.getenv("FLOODCAT_AI_PROVIDER", "").strip().lower()
    if chosen and chosen not in PROVIDERS:
        raise ModelError(
            "ai_unavailable",
            f"FLOODCAT_AI_PROVIDER must be one of {', '.join(PROVIDERS)}",
        )
    return chosen or None


def configured():
    """Providers this server can call, in a stable order."""
    out = []
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        out.append("gemini")
    if os.getenv("OLLAMA_MODEL"):
        out.append("ollama")
    return out


def provider():
    """The server default: FLOODCAT_AI_PROVIDER if set, else Gemini when configured, else Ollama, else None."""
    chosen = _env_provider()
    if chosen:
        return chosen
    return (configured() or [None])[0]


def available():
    try:
        _env_provider()
    except ModelError:
        return False
    return bool(configured())


def choose(settings=None, user_id=None, client_data=False):
    """Return (provider, reason) for one request, or raise ModelError explaining why no model may be used."""
    settings = settings or {}
    allowed = [
        p for p in (settings.get("ai_providers") or PROVIDERS) if p in configured()
    ]
    if not allowed:
        raise ModelError(
            "ai_unavailable",
            "No AI model your organisation allows is configured on this server",
        )
    if client_data and settings.get("ai_local_for_client_data"):
        allowed = [p for p in allowed if p == "ollama"]
        if not allowed:
            raise ModelError(
                "ai_unavailable",
                "Your organisation keeps client data on its own server, but no local model is configured here; "
                "nothing was sent",
            )
    preference = (
        (settings.get("ai_preferences") or {}).get(user_id) if user_id else None
    )
    if preference in allowed:
        return preference, "your preference"
    if settings.get("ai_default_provider") in allowed:
        return settings["ai_default_provider"], "organisation default"
    server = _env_provider()
    if server in allowed:
        return server, "server default"
    return allowed[0], "only model allowed" if len(
        allowed
    ) == 1 else "first model allowed"


def make_client(chosen=None):
    chosen = chosen or provider()
    if chosen == "ollama":
        if not os.getenv("OLLAMA_MODEL"):
            raise ModelError("ai_unavailable", "Set OLLAMA_MODEL to use a local model")
        from .ollama import OllamaClient

        return OllamaClient()
    if chosen == "gemini":
        from .gemini import GeminiClient

        return GeminiClient()
    raise ModelError(
        "ai_unavailable",
        "AI is off: set GEMINI_API_KEY, or OLLAMA_MODEL for a local Ollama model",
    )


def describe(chosen=None):
    """Short label for the interface, e.g. 'Ollama llama3.2:3b (local)'."""
    chosen = chosen or (provider() if available() else None)
    if chosen == "ollama":
        return f"Ollama {os.getenv('OLLAMA_MODEL')} (local)"
    if chosen == "gemini":
        return "Google Gemini"
    return "not configured"
