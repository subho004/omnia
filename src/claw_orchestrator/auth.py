import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from .config import Settings
from .db import Database
from .errors import APIError

CONTROL_COOKIE = "__Host-claw_session"
PROXY_COOKIE = "__Host-claw_proxy"
PRELOGIN_COOKIE = "__Host-claw_prelogin"
USERS = {"user1": "User1", "user2": "User2"}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def workspace_session(sid: str) -> str:
    """Non-secret page fence, never an authentication credential."""
    return digest("claw-workspace:" + sid)


@dataclass(frozen=True)
class Principal:
    sid: str
    user_id: str
    csrf: str
    expires_at: datetime
    instance_id: str | None = None


class Auth:
    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db

    def encode(self, claims: dict, audience: str, expires_at: datetime) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                **claims,
                "iss": "claw-orchestrator",
                "aud": audience,
                "iat": now,
                "nbf": now,
                "exp": expires_at,
                "jti": secrets.token_urlsafe(24),
            },
            self.settings.jwt_secret.get_secret_value(),
            algorithm="HS256",
        )

    def decode(self, token: str | None, audience: str) -> dict:
        if not token:
            raise APIError(401, "AUTH_REQUIRED", "Sign in to continue.")
        try:
            return jwt.decode(
                token,
                self.settings.jwt_secret.get_secret_value(),
                algorithms=["HS256"],
                issuer="claw-orchestrator",
                audience=audience,
                options={"require": ["iss", "aud", "iat", "nbf", "exp", "jti"]},
            )
        except jwt.InvalidTokenError:
            raise APIError(401, "INVALID_SESSION", "Your session is invalid or expired.") from None

    async def authenticate(self, token: str | None, audience: str) -> Principal:
        claims = self.decode(token, audience)
        if (
            claims.get("sub") not in USERS
            or not isinstance(claims.get("sid"), str)
            or not isinstance(claims.get("jti"), str)
            or any(type(claims.get(k)) is not int for k in ("iat", "nbf", "exp"))
        ):
            raise APIError(401, "INVALID_SESSION", "Your session is invalid or expired.")
        async with self.db.connection() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sessions WHERE sid=$1 AND user_id=$2 AND revoked_at IS NULL "
                "AND expires_at>now()",
                claims["sid"],
                claims["sub"],
            )
        if not row or claims["exp"] > row["expires_at"].timestamp():
            raise APIError(401, "INVALID_SESSION", "Your session is invalid or expired.")
        iid = claims.get("iid")
        if audience == "claw-proxy" and not isinstance(iid, str):
            raise APIError(401, "INVALID_SESSION", "Your session is invalid or expired.")
        return Principal(row["sid"], row["user_id"], row["csrf_token"], row["expires_at"], iid)

    async def is_live(self, principal: Principal) -> bool:
        async with self.db.connection() as conn:
            return bool(
                await conn.fetchval(
                    "SELECT 1 FROM sessions WHERE sid=$1 AND user_id=$2 "
                    "AND revoked_at IS NULL AND expires_at>now()",
                    principal.sid,
                    principal.user_id,
                )
            )

    def prelogin(self) -> tuple[str, str]:
        csrf = secrets.token_urlsafe(32)
        token = self.encode(
            {"csrf": csrf}, "claw-prelogin", datetime.now(UTC) + timedelta(minutes=10)
        )
        return csrf, token

    def check_prelogin(self, token: str | None, csrf: str) -> None:
        claims = self.decode(token, "claw-prelogin")
        if not isinstance(claims.get("csrf"), str) or not secrets.compare_digest(
            claims["csrf"], csrf
        ):
            raise APIError(403, "INVALID_CSRF", "Reload the page and try again.")

    async def create_session(self, user_id: str, previous: Principal | None) -> Principal:
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires = datetime.now(UTC).replace(microsecond=0) + timedelta(
            seconds=self.settings.session_seconds
        )
        async with self.db.connection() as conn, conn.transaction():
            if previous:
                result = await conn.execute(
                    "UPDATE sessions SET revoked_at=now() WHERE sid=$1 AND user_id=$2 "
                    "AND revoked_at IS NULL AND expires_at>now()",
                    previous.sid,
                    previous.user_id,
                )
                if result != "UPDATE 1":
                    raise APIError(401, "INVALID_SESSION", "Your session has ended.")
            await conn.execute(
                "INSERT INTO sessions(sid,user_id,csrf_token,expires_at) VALUES($1,$2,$3,$4)",
                sid,
                user_id,
                csrf,
                expires,
            )
        return Principal(sid, user_id, csrf, expires)

    def session_token(self, principal: Principal, audience: str, iid: str | None = None) -> str:
        claims = {"sub": principal.user_id, "sid": principal.sid}
        if iid:
            claims["iid"] = iid
        return self.encode(claims, audience, principal.expires_at)

    async def revoke(self, principal: Principal) -> None:
        async with self.db.connection() as conn:
            await conn.execute("UPDATE sessions SET revoked_at=now() WHERE sid=$1", principal.sid)


def check_csrf(principal: Principal, supplied: str) -> None:
    if not supplied or not secrets.compare_digest(principal.csrf, supplied):
        raise APIError(403, "INVALID_CSRF", "Reload the page and try again.")


def set_cookie(response, name: str, token: str, max_age: int) -> None:
    response.set_cookie(
        name, token, max_age=max_age, secure=True, httponly=True, samesite="lax", path="/"
    )


def clear_cookie(response, name: str) -> None:
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
