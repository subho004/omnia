import ipaddress
import re
import socket
from typing import Literal
from urllib.parse import quote, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_db: str = "claw_orchestrator"
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_app_password: SecretStr
    jwt_secret: SecretStr
    demo_auth_enabled: bool = False
    control_origin: str = "https://app.localhost:8443"
    instance_domain: str = "claw.localhost"
    public_port: int = 8443
    session_seconds: int = 3600
    local_client_address: str | None = None
    inference_provider: Literal["lmstudio", "openrouter"] = "lmstudio"
    egress_proxy_host: str = "0.0.0.0"
    egress_proxy_port: int = 18490
    lmstudio_api_key: SecretStr | None = Field(default=None, repr=False)
    openrouter_api_key: SecretStr | None = Field(default=None, repr=False)
    openrouter_base_url: Literal["https://openrouter.ai/api/v1"] = "https://openrouter.ai/api/v1"
    openrouter_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    openrouter_context_window: int = Field(default=1000000, ge=32768, le=1000000)
    openrouter_max_tokens: int = Field(default=4096, ge=64, le=8192)

    @field_validator("openrouter_model")
    @classmethod
    def free_model_only(cls, value: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*:free", value):
            raise ValueError("Select an explicit :free model; paid/random fallback is disabled")
        return value

    @model_validator(mode="after")
    def validate_local(self):
        origin = urlsplit(self.control_origin)
        if (
            origin.scheme != "https"
            or origin.hostname != "app.localhost"
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
            or origin.username
            or origin.password
            or origin.port != self.public_port
        ):
            raise ValueError(
                "The prototype control origin must be https://app.localhost:PUBLIC_PORT"
            )
        self.control_origin = self.control_origin.rstrip("/")
        if self.instance_domain != "claw.localhost":
            raise ValueError("Demo instance hosts must be under claw.localhost")
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 random bytes")
        if not self.postgres_app_password.get_secret_value():
            raise ValueError("POSTGRES_APP_PASSWORD is required")
        if not 1 <= self.session_seconds <= 3600:
            raise ValueError("Session lifetime must be 1..3600 seconds")
        return self

    def proxy_client_address(self) -> str:
        # All supported demo clients run on this host. OpenClaw requires a non-loopback
        # attributed client even for loopback proxy ingress, so use this host's routed
        # interface address. This is diagnostic/rate-limit attribution, never tenant authority.
        address = self.local_client_address
        if not address:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("192.0.2.1", 9))  # UDP connect discovers the route; sends no packet.
                address = probe.getsockname()[0]
        parsed = ipaddress.ip_address(address)
        if parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast:
            raise ValueError("LOCAL_CLIENT_ADDRESS must identify this host's routed interface")
        return str(parsed)

    @property
    def database_url(self) -> str:
        password = quote(self.postgres_app_password.get_secret_value(), safe="")
        database = quote(self.postgres_db, safe="")
        return (
            f"postgresql://claw_api:{password}@{self.postgres_host}:{self.postgres_port}/{database}"
        )

    def instance_origin(self, instance_id: str) -> str:
        return f"https://{instance_id}.{self.instance_domain}:{self.public_port}"
