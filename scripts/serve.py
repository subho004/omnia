"""Run the prototype on loopback HTTPS with proxy-header trust disabled."""

from pathlib import Path

import uvicorn

from claw_orchestrator.config import Settings

root = Path(__file__).resolve().parents[1]
settings = Settings()
cert, key = root / ".certs/local.pem", root / ".certs/local-key.pem"
if not cert.exists() or not key.exists():
    raise SystemExit(
        "Generate .certs/local.pem and .certs/local-key.pem with mkcert first (README)."
    )

uvicorn.run(
    "claw_orchestrator.app:create_app",
    factory=True,
    host="127.0.0.1",
    port=settings.public_port,
    workers=1,
    proxy_headers=False,
    ssl_certfile=str(cert),
    ssl_keyfile=str(key),
    access_log=False,
    ws_max_size=2 * 1024 * 1024,
    timeout_graceful_shutdown=10,
)
