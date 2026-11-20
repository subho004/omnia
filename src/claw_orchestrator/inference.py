"""Host-side provider preflight; no browser route or tenant credential exposure."""

import httpx

from .config import Settings


class InferenceCheckError(RuntimeError):
    """Safe operator error: never retain the upstream body or request headers."""


async def openrouter_preflight(settings: Settings, client: httpx.AsyncClient) -> dict:
    key = settings.openrouter_api_key
    if not key or not key.get_secret_value().strip():
        raise InferenceCheckError("OPENROUTER_API_KEY is missing")
    headers = {"Authorization": "Bearer " + key.get_secret_value()}
    response = await client.get(settings.openrouter_base_url + "/key", headers=headers)
    if response.status_code != 200:
        raise InferenceCheckError(
            f"OpenRouter credential check failed (HTTP {response.status_code})"
        )
    quota = response.json().get("data", {}).get("free_model_daily_requests", {})
    response = await client.get(settings.openrouter_base_url + "/models")
    if response.status_code != 200:
        raise InferenceCheckError(f"OpenRouter catalog unavailable (HTTP {response.status_code})")
    model = next(
        (m for m in response.json().get("data", []) if m.get("id") == settings.openrouter_model),
        None,
    )
    if not model:
        raise InferenceCheckError("The selected free model is no longer listed")
    pricing = model.get("pricing", {})
    if pricing.get("prompt") != "0" or pricing.get("completion") != "0":
        raise InferenceCheckError("The selected model is not zero-priced; refusing inference")
    if not {"tools", "tool_choice"}.issubset(model.get("supported_parameters", [])):
        raise InferenceCheckError("The selected endpoint does not advertise required tool support")
    if model.get("context_length", 0) < settings.openrouter_context_window:
        raise InferenceCheckError("Configured context exceeds the current endpoint context")
    return {
        "model": settings.openrouter_model,
        "context_length": model["context_length"],
        "configured_context": settings.openrouter_context_window,
        "supports_structured_output": {"response_format", "structured_outputs"}.issubset(
            model.get("supported_parameters", [])
        ),
        "free_model_daily_requests": quota,
    }
