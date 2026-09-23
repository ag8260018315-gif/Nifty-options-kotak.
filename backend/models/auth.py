from typing import Literal

from pydantic import BaseModel


AuthMode = Literal["DEMO", "LIVE"]
AuthState = Literal["DEMO", "DISCONNECTED", "LIVE", "EXPIRED"]


class AuthStatus(BaseModel):
    mode: AuthMode
    state: AuthState
    configured: bool
    connected: bool
    message: str


class DemoModeRequest(BaseModel):
    confirm: bool


class KotakConnectRequest(BaseModel):
    totp: str | None = None
    mpin: str | None = None