from fastapi import APIRouter, HTTPException

from lib.settings import settings
from models.auth import AuthStatus, DemoModeRequest, KotakConnectRequest


router = APIRouter(prefix="/auth", tags=["auth"])


def current_status() -> AuthStatus:
    configured = settings.live_configured
    return AuthStatus(
        mode="LIVE" if settings.mode == "LIVE" and configured else "DEMO",
        state="DISCONNECTED" if configured else "DEMO",
        configured=configured,
        connected=False,
        message=(
            "Kotak credentials are present server-side; live v6 login is ready for the next integration step."
            if configured
            else "DEMO mode is active. Add Kotak credentials to backend/.env before enabling live data."
        ),
    )


@router.get("/status", response_model=AuthStatus)
async def get_auth_status() -> AuthStatus:
    return current_status()


@router.post("/demo", response_model=AuthStatus)
async def confirm_demo_mode(request: DemoModeRequest) -> AuthStatus:
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Demo mode requires explicit confirmation")
    return current_status()


@router.post("/connect", response_model=AuthStatus)
async def connect_kotak(request: KotakConnectRequest) -> AuthStatus:
    del request
    if not settings.live_configured:
        raise HTTPException(
            status_code=409,
            detail="Kotak credentials are not configured. Add them server-side in backend/.env.",
        )
    raise HTTPException(
        status_code=501,
        detail="Live Kotak v6 authentication is reserved for the credentialed integration step.",
    )