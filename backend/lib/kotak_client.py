import logging
import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
import pyotp

from lib.settings import settings
from lib.token_vault import vault
from lib.db import db


logger = logging.getLogger(__name__)
LOGIN_URL = "https://mis.kotaksecurities.com/login/1.0/tradeApiLogin"
VALIDATE_URL = "https://mis.kotaksecurities.com/login/1.0/tradeApiValidate"


@dataclass
class KotakSession:
    token: str
    sid: str
    base_url: str
    feed_url: str | None
    expires_at: float


def _payload(response: dict[str, Any]) -> dict[str, Any]:
    value = response.get("data", response)
    return value if isinstance(value, dict) else {}


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
    return None


def _service_url(value: Any, schemes: tuple[str, ...]) -> str | None:
    if not isinstance(value, str) or not re.match(rf"^({'|'.join(schemes)})://", value):
        return None
    return value.rstrip("/")


class KotakNeoClient:
    def __init__(self) -> None:
        self.session: KotakSession | None = None

    @property
    def connected(self) -> bool:
        return bool(self.session and self.session.expires_at > time.time() + 30)

    async def login(self) -> KotakSession:
        if not settings.live_configured:
            raise RuntimeError("live Kotak configuration is incomplete")
        if not vault.configured:
            raise RuntimeError("KOTAK_VAULT_KEY is required before starting live login")
        headers = {
            "Authorization": settings.access_token,
            "neo-fin-key": settings.neo_fin_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                login_response = await client.post(
                    LOGIN_URL,
                    headers=headers,
                    json={
                        "mobileNumber": settings.mobile_number,
                        "ucc": settings.ucc,
                        "totp": pyotp.TOTP(settings.totp_secret).now(),
                    },
                )
                login_response.raise_for_status()
                first = _payload(login_response.json())
                view_sid = _pick(first, "viewSid", "sid", "Sid")
                view_token = _pick(first, "viewToken", "Auth", "auth", "token")
                if not view_sid or not view_token:
                    raise RuntimeError("unexpected tradeApiLogin response shape")

                validate_response = await client.post(
                    VALIDATE_URL,
                    headers={**headers, "sid": str(view_sid), "Auth": str(view_token)},
                    json={"mpin": settings.mpin},
                )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                login_response = await client.post(
                    LOGIN_URL,
                    headers=headers,
                    json={
                        "mobileNumber": settings.mobile_number,
                        "ucc": settings.ucc,
                        "totp": pyotp.TOTP(settings.totp_secret).now(),
                    },
                )
                login_response.raise_for_status()
                first = _payload(login_response.json())
                view_sid = _pick(first, "viewSid", "sid", "Sid")
                view_token = _pick(first, "viewToken", "Auth", "auth", "token")
                if not view_sid or not view_token:
                    raise RuntimeError("unexpected tradeApiLogin response shape")

                validate_response = await client.post(
                    VALIDATE_URL,
                    headers={**headers, "sid": str(view_sid), "Auth": str(view_token)},
                    json={"mpin": settings.mpin},
                )
                validate_response.raise_for_status()
                result = _payload(validate_response.json())

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Kotak v2 authentication rejected status=%s body=%s",
                exc.response.status_code,
                exc.response.text[:1000],
            )
            raise RuntimeError("Kotak authentication was rejected") from exc

        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Kotak v2 authentication transport/JSON error")
            raise RuntimeError("Kotak authentication failed") from exc

        token = _pick(result, "Auth", "auth", "token", "accessToken")
        sid = _pick(result, "Sid", "sid", "sessionId")
        base_url = _service_url(_pick(result, "baseUrl", "baseURL"), ("https",))
        feed_url = _service_url(_pick(result, "feedUrl", "feedURL"), ("https", "wss"))
        if not token or not sid or not base_url:
            raise RuntimeError("tradeApiValidate did not return token, sid, and baseUrl")

        self.session = KotakSession(
            token=str(token),
            sid=str(sid),
            base_url=base_url,
            feed_url=feed_url,
            expires_at=time.time() + 8 * 60 * 60,
        )
        await db.kotak_sessions.update_one(
            {"_id": "current"},
            {
                "$set": {
                    "token": vault.seal(self.session.token),
                    "sid": vault.seal(self.session.sid),
                    "base_url": vault.seal(self.session.base_url),
                    "feed_url": vault.seal(self.session.feed_url or ""),
                    "expires_at": self.session.expires_at,
                    "updated_at": time.time(),
                }
            },
            upsert=True,
        )
        return self.session

    async def restore_session(self) -> KotakSession | None:
        if self.connected:
            return self.session
        try:
            document = await db.kotak_sessions.find_one({"_id": "current"})
            if not document or float(document.get("expires_at", 0)) <= time.time() + 30:
                return None
            base_url = _service_url(vault.open(document["base_url"]), ("https",))
            feed_url = _service_url(vault.open(document["feed_url"]), ("https", "wss"))
            if not base_url or not feed_url:
                return None
            self.session = KotakSession(
                token=vault.open(document["token"]),
                sid=vault.open(document["sid"]),
                base_url=base_url,
                feed_url=feed_url,
                expires_at=float(document["expires_at"]),
            )
            return self.session
        except Exception:
            logger.warning("Stored Kotak session could not be restored")
            return None

    async def ensure_session(self) -> KotakSession:
        if self.connected and self.session:
            return self.session
        restored = await self.restore_session()
        return restored or await self.login()

    def clear_session(self) -> None:
        self.session = None

    async def authenticated_get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        session = await self.ensure_session()
        url = f"{session.base_url}/{path.lstrip('/')}"
        headers = {"Authorization": settings.access_token, "Content-Type": "application/x-www-form-urlencoded"}
        for attempt in range(3):
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=headers, params=params)
            if response.status_code != 429 or attempt == 2:
                response.raise_for_status()
                body = response.json()
                return body if isinstance(body, dict) else {"data": body}
            retry_after = response.headers.get("Retry-After", "1")
            await asyncio.sleep(min(max(float(retry_after), 1), 10))
        raise RuntimeError("Kotak request retry loop exited unexpectedly")


kotak_client = KotakNeoClient()
