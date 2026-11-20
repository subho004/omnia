"""Generate private local configuration once, without printing any credentials."""

import os
import secrets
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / ".env"
    if path.exists():
        print(".env already exists; kept its contents. Compare with .env.example for new settings.")
        return
    values = {
        "POSTGRES_DB": "claw_orchestrator",
        "POSTGRES_USER": "claw_admin",
        "POSTGRES_PASSWORD": secrets.token_urlsafe(40),
        "POSTGRES_APP_PASSWORD": secrets.token_urlsafe(40),
        "POSTGRES_PORT": "5432",
        "JWT_SECRET": secrets.token_urlsafe(48),
        "DEMO_AUTH_ENABLED": "true",
        "CONTROL_ORIGIN": "https://app.localhost:8443",
        "INSTANCE_DOMAIN": "claw.localhost",
        "PUBLIC_PORT": "8443",
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("# Generated local secrets. Do not commit or copy into tenant workloads.\n")
        stream.writelines(f"{key}={value}\n" for key, value in values.items())
    (root / "db").mkdir(exist_ok=True)
    print("Created private .env and db/. Start PostgreSQL with docker compose up -d --wait db.")


if __name__ == "__main__":
    main()
