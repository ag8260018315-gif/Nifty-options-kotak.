import logging
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


def _https_url(value: Any) -> str | None:
    if not isinstance(value, str) or not re.match(r"^https://", value):
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
                validate_response.raise_for_status()
                result = _payload(validate_response.json())
        except httpx.HTTPStatusError as exc:
            logger.warning("Kotak v2 authentication rejected with status %s", exc.response.status_code)
            raise RuntimeError("Kotak authentication was rejected") from exc
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Kotak v2 authentication transport/JSON error")
            raise RuntimeError("Kotak authentication failed") from exc

        token = _pick(result, "Auth", "auth", "token", "accessToken")
        sid = _pick(result, "Sid", "sid", "sessionId")
        base_url = _https_url(_pick(result, "baseUrl", "baseURL"))
        feed_url = _https_url(_pick(result, "feedUrl", "feedURL"))
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

    async def authenticated_get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.connected:
            await self.login()
        assert self.session is not None
        url = f"{self.session.base_url}/{path.lstrip('/')}"
        headers = {"Authorization": self.session.token, "Sid": self.session.sid, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            body = response.json()
        return body if isinstance(body, dict) else {"data": body}


kotak_client = KotakNeoClient()