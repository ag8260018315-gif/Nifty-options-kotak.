"""Invite-only email sign-in with one-time codes.

Configuration (Render -> Environment). Nothing here is ever sent to the browser.
  AUTH_REQUIRED    "true" locks every protected /api route. Anything else leaves the app open
                   (so this can be deployed before the frontend and switched on afterwards).
  AUTH_SECRET      long random string used to sign session cookies and hash codes.
  ADMIN_EMAILS     comma-separated; admins may also press Connect Kotak and change alert settings.
  ALLOWED_EMAILS   comma-separated viewers who may sign in.
  SMTP_USERNAME    the Gmail address that sends the codes.
  SMTP_PASSWORD    the Gmail app password (spaces are ignored).
  SMTP_HOST/PORT   default smtp.gmail.com / 587.  SMTP_FROM defaults to SMTP_USERNAME.
  SESSION_DAYS     how long a sign-in lasts, default 7.
"""
import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request

logger = logging.getLogger(__name__)

COOKIE_NAME = "nod_session"
CODE_TTL_SECONDS = 10 * 60
RESEND_COOLDOWN_SECONDS = 60
MAX_SENDS_PER_HOUR = 5
MAX_ATTEMPTS = 5
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
_collection_override: Any | None = None  # tests inject a fake collection


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def auth_required() -> bool:
    return _env("AUTH_REQUIRED").lower() in {"1", "true", "yes", "on"}


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match(value))


def _email_set(name: str) -> set[str]:
    return {normalize_email(item) for item in _env(name).split(",") if item.strip()}


def admin_emails() -> set[str]:
    return _email_set("ADMIN_EMAILS")


def role_for(email: str) -> str | None:
    email = normalize_email(email)
    if email in admin_emails():
        return "admin"
    if email in _email_set("ALLOWED_EMAILS"):
        return "viewer"
    return None


def _secret() -> str:
    return _env("AUTH_SECRET")


def sign_in_configured() -> bool:
    return bool(len(_secret()) >= 16 and _env("SMTP_USERNAME") and _env("SMTP_PASSWORD") and admin_emails())


def _session_days() -> int:
    try:
        return min(30, max(1, int(_env("SESSION_DAYS", "7"))))
    except ValueError:
        return 7


def _code_hash(email: str, code: str) -> str:
    return hmac.new(_secret().encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _collection() -> Any:
    if _collection_override is not None:
        return _collection_override
    from lib.db import db

    return db["access_codes"]


# ---------------------------------------------------------------------------- email
def _send_email_sync(to_address: str, code: str) -> None:
    username = _env("SMTP_USERNAME")
    password = _env("SMTP_PASSWORD").replace(" ", "")
    host = _env("SMTP_HOST", "smtp.gmail.com")
    port = int(_env("SMTP_PORT", "587") or 587)
    message = EmailMessage()
    message["Subject"] = f"{code} is your NIFTY Options Desk sign-in code"
    message["From"] = _env("SMTP_FROM") or username
    message["To"] = to_address
    message.set_content(
        f"Your sign-in code is {code}\n\n"
        "It expires in 10 minutes and can be used once.\n"
        "If you did not try to sign in, you can ignore this email.\n"
    )
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(username, password)
            server.send_message(message)


async def send_code(email: str) -> None:
    """Create a code for an approved email and send it. Raises HTTPException for the router."""
    if not sign_in_configured():
        raise HTTPException(status_code=503, detail="Email sign-in isn't set up on the server yet.")
    email = normalize_email(email)
    if not valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if role_for(email) is None:
        raise HTTPException(status_code=403, detail="This email isn't approved yet. Ask the owner to add it.")
    now = time.time()
    collection = _collection()
    existing = await collection.find_one({"_id": email}) or {}
    recent = [stamp for stamp in existing.get("sends", []) if now - stamp < 3600]
    if recent and now - max(recent) < RESEND_COOLDOWN_SECONDS:
        wait = int(RESEND_COOLDOWN_SECONDS - (now - max(recent))) + 1
        raise HTTPException(status_code=429, detail=f"A code was just sent. Try again in {wait} seconds.")
    if len(recent) >= MAX_SENDS_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many codes requested. Try again in an hour.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        await asyncio.to_thread(_send_email_sync, email, code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ACCESS_EMAIL_ERROR kind=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="The code email couldn't be sent. Try again shortly.") from exc
    await collection.replace_one(
        {"_id": email},
        {"_id": email, "code_hash": _code_hash(email, code), "expires_at": now + CODE_TTL_SECONDS, "attempts": 0, "sends": recent + [now]},
        upsert=True,
    )
    logger.info("ACCESS_CODE_SENT role=%s", role_for(email))


async def verify_code(email: str, code: str) -> dict[str, str]:
    email = normalize_email(email)
    code = re.sub(r"\D", "", code or "")
    role = role_for(email)
    if not sign_in_configured():
        raise HTTPException(status_code=503, detail="Email sign-in isn't set up on the server yet.")
    if role is None:
        raise HTTPException(status_code=403, detail="This email isn't approved yet. Ask the owner to add it.")
    collection = _collection()
    record = await collection.find_one({"_id": email})
    now = time.time()
    if not record or not record.get("code_hash") or record.get("expires_at", 0) < now:
        raise HTTPException(status_code=400, detail="That code has expired. Request a new one.")
    if record.get("attempts", 0) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many wrong codes. Request a new one.")
    if len(code) != 6 or not hmac.compare_digest(record["code_hash"], _code_hash(email, code)):
        await collection.update_one({"_id": email}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400, detail="That code isn't right. Check the email and try again.")
    await collection.update_one({"_id": email}, {"$unset": {"code_hash": "", "expires_at": ""}, "$set": {"attempts": 0}})
    logger.info("ACCESS_SIGNED_IN role=%s", role)
    return {"email": email, "role": role}


# ---------------------------------------------------------------------------- sessions
def issue_session(email: str, role: str) -> tuple[str, int]:
    max_age = _session_days() * 86400
    now = int(time.time())
    token = jwt.encode({"sub": email, "role": role, "iat": now, "exp": now + max_age}, _secret(), algorithm="HS256")
    return token, max_age


def read_session(token: str | None) -> dict[str, str] | None:
    if not token or len(_secret()) < 16:
        return None
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    email = normalize_email(str(claims.get("sub", "")))
    role = role_for(email)  # re-checked every request: removing an email revokes access at once
    if role is None:
        return None
    return {"email": email, "role": role}


def cookie_settings(max_age: int) -> dict[str, Any]:
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "secure": _env("COOKIE_SECURE", "true").lower() != "false",
        "samesite": "strict",
        "path": "/api",
        "max_age": max_age,
    }


OPEN_USER = {"email": None, "role": "admin"}


async def require_user(request: Request) -> dict[str, Any]:
    if not auth_required():
        return OPEN_USER
    user = read_session(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user


async def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only the owner can do this.")
    return user
