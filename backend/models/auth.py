from typing import Literal

from pydantic import BaseModel


AuthMode = Literal["DEMO", "LIVE"]
AuthState = Literal["DEMO", "DISCONNECTED", "LIVE", "EXPIRED"]


class AuthStatus(BaseModel):
    mode: AuthMode
    state: AuthState
    configured: bool
    connected: bool
    configured_fields: list[str]
    missing_fields: list[str]
    feed_connected: bool
    message: str


class DemoModeRequest(BaseModel):
    confirm: bool


class KotakConnectRequest(BaseModel):
    """The browser sends no credentials; the server generates TOTP and reads MPIN."""