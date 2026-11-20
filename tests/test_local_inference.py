from uuid import uuid4

from claw_orchestrator.config import Settings
from claw_orchestrator.presentation import public_text
from claw_orchestrator.runtime.nemoclaw import NemoClawRuntime


def test_local_token_is_not_forwarded_to_routine_tenant_commands(test_settings, monkeypatch):
    secret = "sk-lm-fixture:private-test-token-not-a-real-key"
    monkeypatch.setenv("LMSTUDIO_API_KEY", secret)
    monkeypatch.setenv("COMPATIBLE_API_KEY", secret)
    settings = Settings(
        **{
            **test_settings.model_dump(),
            "inference_provider": "lmstudio",
            "lmstudio_api_key": secret,
        }
    )
    runtime = NemoClawRuntime(settings, validate_setup=False)
    row = {"id": uuid4(), "owner_user_id": "user1"}
    runtime.bind(row)
    routine = runtime.environment(str(row["id"]))
    assert "LMSTUDIO_API_KEY" not in routine and "COMPATIBLE_API_KEY" not in routine
    assert "NEMOCLAW_COMPATIBLE_AUTH_MODE" not in routine
    privileged = runtime.environment(str(row["id"]), inference_credentials=True)
    assert privileged["COMPATIBLE_API_KEY"] == secret
    assert secret not in repr(settings)


def test_local_token_redacts_colon_separated_secret_completely():
    text = "Authorization: Bearer sk-lm-fixture:private-test-token-not-a-real-key"
    result = public_text(text)
    assert "fixture" not in result and "private-test-token" not in result
