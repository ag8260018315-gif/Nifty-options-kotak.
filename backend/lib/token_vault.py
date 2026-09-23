"""Small server-only encryption primitive for future Kotak session material.

The current DEMO build never receives or persists a Kotak token. Once live auth is
enabled, the integration service should encrypt token/sid/baseUrl values with a
deployment-provided KOTAK_VAULT_KEY before writing them to MongoDB.
"""

import os

from cryptography.fernet import Fernet, InvalidToken


class TokenVault:
    def __init__(self, key: str | None = None):
        self._key = key or os.environ.get("KOTAK_VAULT_KEY", "")

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def seal(self, value: str) -> str:
        if not self._key:
            raise RuntimeError("KOTAK_VAULT_KEY is not configured")
        return Fernet(self._key.encode()).encrypt(value.encode()).decode()

    def open(self, value: str) -> str:
        if not self._key:
            raise RuntimeError("KOTAK_VAULT_KEY is not configured")
        try:
            return Fernet(self._key.encode()).decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("invalid encrypted Kotak session material") from exc


vault = TokenVault()