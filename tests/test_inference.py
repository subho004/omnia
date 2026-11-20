import json
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from claw_orchestrator.config import Settings
from claw_orchestrator.inference import InferenceCheckError, openrouter_preflight
from claw_orchestrator.runtime import NemoClawRuntime


def settings(**kwargs):
    return Settings(
        _env_file=None,
        postgres_app_password="test-password",
        jwt_secret="x" * 40,
        openrouter_api_key="test-provider-secret",
        inference_provider="openrouter",
        **kwargs,
    )


def test_provider_settings_cannot_route_secret_to_another_host_or_paid_model():
    with pytest.raises(ValidationError):
        settings(openrouter_base_url="https://example.invalid/api/v1")
    for model in ("openrouter/free", "z-ai/glm-5.3-flash", "../keys:free"):
        with pytest.raises(ValidationError):
            settings(openrouter_model=model)
    assert "test-provider-secret" not in repr(settings())


def test_native_provider_key_only_reaches_explicit_onboarding_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "inherited-secret")
    runtime = NemoClawRuntime.__new__(NemoClawRuntime)
    runtime.settings = settings()
    runtime.state = Path("/tmp/test-runtime")
    runtime.manifest = {
        "gateway_port": 18480,
        "inference_endpoint": "http://127.0.0.1:1234/v1",
        "inference_model": "legacy-local-model",
    }
    runtime.bindings = {}
    first, second = str(uuid4()), str(uuid4())
    runtime.bind({"id": first, "owner_user_id": "user1"})
    runtime.bind({"id": second, "owner_user_id": "user2"})
    for iid, port in ((first, "18480"), (second, "18481")):
        env = runtime.environment(iid)
        assert "OPENROUTER_API_KEY" not in env
        assert env["NEMOCLAW_PROVIDER"] == "openrouter"
        assert env["NEMOCLAW_GATEWAY_PORT"] == port
        assert env["OPENSHELL_GATEWAY"] == f"nemoclaw-{port}"
        assert env["OPENSHELL_WORKSPACE"] == "default"
        assert env["NEMOCLAW_MODEL"].endswith(":free")
        assert "NEMOCLAW_VLLM_PORT" not in env
        onboarding = runtime.environment(iid, inference_credentials=True)
        assert onboarding["OPENROUTER_API_KEY"] == "test-provider-secret"
        assert onboarding["CLAW_ORCHESTRATOR_INSTANCE_ID"] == iid


async def test_native_command_redacts_provider_key_from_log_and_returned_output(tmp_path):
    runtime = NemoClawRuntime.__new__(NemoClawRuntime)
    runtime.settings = settings()
    runtime.root = tmp_path
    runtime.metadata = tmp_path
    runtime.environment = lambda iid, **kwargs: {}
    iid = str(uuid4())
    result = await runtime.command([sys.executable, "-c", "print('test-provider-secret')"], iid)
    assert "test-provider-secret" not in result
    assert "REDACTED_PROVIDER_KEY" in result
    assert "test-provider-secret" not in (tmp_path / f"{iid}.log").read_text()


@pytest.mark.parametrize("failure", [None, "auth", "paid", "tools", "context", "retired"])
async def test_preflight_rejects_changed_provider_contract_without_leaking_key(failure):
    config = settings()
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/key"):
            if failure == "auth":
                return httpx.Response(401, text="test-provider-secret must not be surfaced")
            return httpx.Response(
                200, json={"data": {"free_model_daily_requests": {"remaining": 50}}}
            )
        model = {
            "id": config.openrouter_model,
            "pricing": {"prompt": "0", "completion": "0"},
            "context_length": 1000000,
            "supported_parameters": ["tools", "tool_choice"],
        }
        if failure == "paid":
            model["pricing"]["completion"] = "0.1"
        if failure == "tools":
            model["supported_parameters"] = []
        if failure == "context":
            model["context_length"] = 8192
        return httpx.Response(200, json={"data": [] if failure == "retired" else [model]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if failure:
            with pytest.raises(InferenceCheckError) as error:
                await openrouter_preflight(config, client)
            assert "test-provider-secret" not in str(error.value)
        else:
            result = await openrouter_preflight(config, client)
            assert result["free_model_daily_requests"]["remaining"] == 50
            assert result["supports_structured_output"] is False
            assert "test-provider-secret" not in json.dumps(result)
    assert seen[0].headers["authorization"] == "Bearer test-provider-secret"
    for request in seen[1:]:
        assert "authorization" not in request.headers
