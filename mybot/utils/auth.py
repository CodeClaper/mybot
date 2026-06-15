"""Authentication and token management for mybot channels."""

import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode


class AuthManager:
    """Issue, verify, and refresh tokens using HMAC-SHA256 signed JWTs.

    Access tokens are short-lived JWTs carrying user identity. Refresh
    tokens are long-lived opaque strings that can be rotated for new
    access tokens.
    """

    def __init__(
        self,
        secret: str = "",
        access_token_ttl: int = 300,
        refresh_token_ttl: int = 30 * 24 * 3600,
        users: dict[str, str] | None = None,
    ) -> None:
        self._secret = secret
        self._access_token_ttl = access_token_ttl
        self._refresh_token_ttl = refresh_token_ttl
        self._users = users or {"username": "superadmin", "password": '123456'}
        # refresh_token_value -> {username, expires_at}
        self._refresh_tokens: dict[str, dict[str, object]] = {}

    # ------------------------------------------------------------------
    # JWT helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _b64encode(data: bytes) -> str:
        return urlsafe_b64encode(data).rstrip(b"=").decode()

    @staticmethod
    def _b64decode(data: str) -> bytes:
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return urlsafe_b64decode(data)

    def _sign(self, payload: str) -> str:
        mac = hmac.new(
            self._secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        )
        return self._b64encode(mac.digest())

    def _encode_jwt(self, payload: dict[str, object]) -> str:
        header = self._b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
        )
        body = self._b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        )
        signature = self._sign(f"{header}.{body}")
        return f"{header}.{body}.{signature}"

    def _decode_jwt(self, token: str) -> dict[str, object] | None:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, body_b64, signature = parts
        expected_sig = self._sign(f"{header_b64}.{body_b64}")
        if not hmac.compare_digest(signature, expected_sig):
            return None
        try:
            return json.loads(self._b64decode(body_b64))
        except (json.JSONDecodeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def issue_token(self, username: str, password: str) -> tuple[str, str] | None:
        """Issue access_token and refresh_token via username/password.

        Returns ``(access_token, refresh_token)`` or ``None`` if credentials
        are invalid.
        """
        expected = self._users.get(username)
        if expected is None or not hmac.compare_digest(expected, password):
            return None

        now = int(time.time())
        access_payload: dict[str, object] = {
            "sub": username,
            "iat": now,
            "exp": now + self._access_token_ttl,
            "type": "access",
        }
        access_token = self._encode_jwt(access_payload)

        refresh_value = secrets.token_urlsafe(32)
        self._refresh_tokens[refresh_value] = {
            "username": username,
            "expires_at": now + self._refresh_token_ttl,
        }

        return access_token, refresh_value

    def verify_access_token(self, token: str) -> dict[str, object] | None:
        """Verify an access token and return its payload, or ``None`` if
        invalid or expired."""
        payload = self._decode_jwt(token)
        if payload is None:
            return None
        if payload.get("type") != "access":
            return None
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload

    def refresh(self, refresh_token: str) -> tuple[str, str] | None:
        """Issue new access and refresh tokens via a valid refresh token.

        Rotates the refresh token: the old one is consumed so each refresh
        token can only be used once. Returns ``(access_token, refresh_token)``
        or ``None`` if invalid or expired.
        """
        stored = self._refresh_tokens.pop(refresh_token, None)
        if stored is None:
            return None
        if int(stored["expires_at"]) < time.time():  # type: ignore[arg-type]
            return None

        username = str(stored["username"])
        now = int(time.time())
        access_payload: dict[str, object] = {
            "sub": username,
            "iat": now,
            "exp": now + self._access_token_ttl,
            "type": "access",
        }
        access_token = self._encode_jwt(access_payload)

        new_refresh = secrets.token_urlsafe(32)
        self._refresh_tokens[new_refresh] = {
            "username": username,
            "expires_at": now + self._refresh_token_ttl,
        }

        return access_token, new_refresh

    def purge_expired_refresh_tokens(self) -> None:
        """Remove expired refresh tokens from the store."""
        now = time.time()
        for key, entry in list(self._refresh_tokens.items()):
            if int(entry["expires_at"]) < now:  # type: ignore[arg-type]
                self._refresh_tokens.pop(key, None)
