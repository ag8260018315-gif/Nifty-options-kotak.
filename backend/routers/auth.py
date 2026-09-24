from fastapi import APIRouter, HTTPException

from lib.kotak_client import kotak_client
from lib.feed_worker import feed_worker
from lib.settings import settings
from models.auth import AuthStatus, DemoModeRequest, KotakConnectRequest


router = APIRouter(prefix="/auth", tags=["auth"])


def current_status() -> AuthStatus:
    required = {
        "KOTAK_ACCESS_TOKEN": settings.access_token,
        "KOTAK_TOTP_SECRET": settings.totp_secret,
        "KOTAK_MPIN": settings.mpin,
        "KOTAK_MOBILE_NUMBER": settings.mobile_number,
        "KOTAK_UCC": settings.ucc,
        "KOTAK_VAULT_KEY": settings.vault_key,
    }
    configured_fields = [name for name, value in required.items() if value]
    missing_fields = [name for name, value in required.items() if not value]
    configured = settings.live_configured
    connected = kotak_client.connected
    state = "LIVE" if connected else "DISCONNECTED" if settings.mode == "LIVE" else "DEMO"
    return AuthStatus(
        mode=settings.mode,
        state=state,
        configured=configured,
        connected=connected,
        configured_fields=configured_fields,
        missing_fields=missing_fields,
        feed_connected=feed_worker.socket_connected,
        message=(
            "Kotak v2 session and SFeed are active server-side; tokens and dynamic URLs never leave FastAPI."
            if connected and feed_worker.socket_connected
            else "Kotak v2 session is active; SFeed is reconnecting or waiting for market ticks."
            if connected
            else "Kotak v2 configuration is complete. Use Connect Kotak Neo to run the server-side TOTP and MPIN flow."
            if configured
            else "DEMO mode is active. Add the current Kotak v2 variables to backend/.env before enabling live data."
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
    if settings.mode != "LIVE":
        raise HTTPException(status_code=409, detail="Set KOTAK_MODE=LIVE server-side before starting a live Kotak session")
    if not settings.live_configured:
        raise HTTPException(
            status_code=409,
            detail="Current Kotak v2 configuration is incomplete. Add the required values server-side in backend/.env.",
        )
    try:
        await kotak_client.login()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail="Kotak v2 authentication failed; inspect redacted backend logs") from exc
    return current_status()