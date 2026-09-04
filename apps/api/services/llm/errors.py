"""Human-friendly diagnostics for LLM provider failures.

Self-hosters see generic errors when a provider is unreachable and have no
idea whether the cause is a wrong URL, a missing model, an invalid key, or a
crashed server. ``describe_llm_error`` classifies a raw exception (or error
string) into one of a few well-known failure modes and returns an actionable
message that names the provider, endpoint, and model.

Classification is substring/pattern based on the error text and exception
class name, so it works uniformly across openai/httpx/aiohttp/stdlib errors
without importing any provider SDK.
"""

from __future__ import annotations

# Env var holding the API key, per cloud provider (used in auth hints)
_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
}

# Local backends where "connection refused" almost always means "not started"
_LOCAL_START_HINTS = {
    "ollama": "start it with `ollama serve`",
    "lmstudio": "open LM Studio and start the local server",
    "vllm": "start the vLLM server",
    "textgenwebui": "start text-generation-webui with --api",
}


def _text_of(error: BaseException | str) -> str:
    if isinstance(error, BaseException):
        return f"{type(error).__name__}: {error}"
    return str(error)


def classify_llm_error(error: BaseException | str) -> str:
    """Classify an LLM failure into a category keyword.

    Returns one of: ``connection_refused`` | ``dns`` | ``timeout`` | ``auth``
    | ``model_not_found`` | ``rate_limit`` | ``unknown``.
    """
    text = _text_of(error).lower()

    if any(p in text for p in (
        "getaddrinfo", "name or service not known", "nodename nor servname",
        "temporary failure in name resolution", "dns",
    )):
        return "dns"
    if any(p in text for p in (
        "connection refused", "connecterror", "connection error",
        "errno 111", "winerror 10061", "all connection attempts failed",
        "cannot connect to host", "connection reset",
    )):
        return "connection_refused"
    if any(p in text for p in ("timed out", "timeout", "deadline exceeded")):
        return "timeout"
    if any(p in text for p in (
        "401", "403", "unauthorized", "forbidden", "invalid api key",
        "incorrect api key", "authenticationerror", "permission",
        "invalid x-api-key", "api key not valid",
    )):
        return "auth"
    if any(p in text for p in (
        "model not found", "model_not_found", "no such model",
        "try pulling it", "does not exist or you do not have access",
        "notfounderror",
    )) or ("404" in text and "model" in text):
        return "model_not_found"
    if any(p in text for p in ("429", "rate limit", "ratelimit", "quota", "overloaded")):
        return "rate_limit"
    return "unknown"


def describe_llm_error(
    error: BaseException | str,
    *,
    provider: str = "llm",
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    """Return an actionable, user-facing message for an LLM failure.

    The full technical error is appended in brackets so support threads keep
    the raw signal; callers should still log the original exception.
    """
    category = classify_llm_error(error)
    endpoint = f" at {base_url}" if base_url else ""
    model_part = f" '{model}'" if model else ""
    raw = _text_of(error)

    if category == "connection_refused":
        hint = _LOCAL_START_HINTS.get(
            provider, "check that the server is running and the URL/port are correct"
        )
        msg = f"Cannot reach {provider}{endpoint} — connection refused; {hint}."
    elif category == "dns":
        msg = (
            f"Cannot resolve the {provider} endpoint{endpoint} — "
            "the hostname looks wrong; check the base URL in settings."
        )
    elif category == "timeout":
        msg = (
            f"{provider}{endpoint} timed out — the model{model_part} may be too "
            "large for the hardware or the server is overloaded; try a smaller "
            "model or increase the timeout."
        )
    elif category == "auth":
        key_env = _KEY_ENV.get(provider)
        key_hint = f"check {key_env}" if key_env else "check the configured API key"
        msg = f"Authentication with {provider} failed — {key_hint} (expired, revoked, or pasted with whitespace?)."
    elif category == "model_not_found":
        if provider == "ollama":
            pull = f"`ollama pull {model}`" if model else "`ollama pull <model>`"
            msg = f"Model{model_part} not found on {provider}{endpoint} — pull it with {pull} or pick an installed model (`ollama list`)."
        else:
            msg = f"Model{model_part} not found on {provider}{endpoint} — check the model name in settings and your account's model access."
    elif category == "rate_limit":
        msg = f"{provider} is rate-limiting or out of quota — wait and retry, or check the plan/quota for this key."
    else:
        msg = f"{provider}{endpoint} request failed — see the technical error below and the server logs."

    return f"{msg} [{raw}]"
