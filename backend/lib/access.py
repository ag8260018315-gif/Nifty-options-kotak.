"""Invite-only email sign-in with one-time codes, access requests and owner approval.

Configuration (Render -> Environment). Nothing here is ever sent to the browser.
  AUTH_REQUIRED    "true" locks every protected /api route. Anything else leaves the app open.
  AUTH_SECRET      long random string used to sign session cookies and hash codes.
  ADMIN_EMAILS     comma-separated owners: they approve requests, press Connect Kotak, etc.
  ALLOWED_EMAILS   optional comma-separated viewers (people approved in the app are stored in MongoDB).
  SMTP_USERNAME    the Gmail address that sends emails.   SMTP_PASSWORD  the Gmail app password.
  SMTP_HOST/PORT   default smtp.gmail.com / 587.          SMTP_FROM defaults to SMTP_USERNAME.
  SESSION_DAYS     how long a sign-in lasts, default 7.   APP_URL  link used in emails.
  SIGNUPS_OPEN     default "true": any email can sign up and gets an automatic free trial.
  TRIAL_DAYS       length of the free trial, default 7.  SIGNUP_CODES_PER_HOUR  cap for new emails, default 40.
Roles: admin (owner), viewer (approved, no expiry), trial (free trial running), expired (trial over).
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
from collections import deque
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
MAX_NEW_REQUESTS_PER_HOUR = 30
USER_CACHE_SECONDS = 30
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
_collection_override: dict[str, Any] = {}  # tests inject fake collections by name
_db_users: dict[str, str] = {}
_db_users_loaded_at = 0.0
_trial_cache: dict[str, tuple[float | None, float]] = {}  # email -> (trial ends_at or None, loaded at)
_signup_codes: deque[float] = deque()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def auth_required() -> bool:
    return _env("AUTH_REQUIRED").lower() in {"1", "true", "yes", "on"}


def normalize_email(value: str) -> str:
    return (value or "").strip().strip("`'\"").strip().lower()


def valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match(value))


def _email_set(name: str) -> set[str]:
    return {normalize_email(item) for item in _env(name).split(",") if normalize_email(item)}


def admin_emails() -> set[str]:
    return _email_set("ADMIN_EMAILS")


def signups_open() -> bool:
    return _env("SIGNUPS_OPEN", "true").lower() not in {"0", "false", "no", "off"}


def trial_days() -> int:
    try:
        return max(0, int(_env("TRIAL_DAYS", "7")))
    except ValueError:
        return 7


def _signup_code_cap() -> int:
    try:
        return max(1, int(_env("SIGNUP_CODES_PER_HOUR", "40")))
    except ValueError:
        return 40


def app_url() -> str:
    return _env("APP_URL", "https://edgedesk.in")


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


def _collection(name: str) -> Any:
    if name in _collection_override:
        return _collection_override[name]
    from lib.db import db

    return db[name]


def _clean_text(value: str | None, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", value or "").strip()
    return text[:limit]


# ---------------------------------------------------------------------------- who has access
async def _load_db_users(force: bool = False) -> dict[str, str]:
    global _db_users, _db_users_loaded_at
    if force or time.monotonic() - _db_users_loaded_at > USER_CACHE_SECONDS:
        try:
            docs = await _collection("access_users").find({}, {"_id": 1}).to_list(5000)
            _db_users = {normalize_email(doc["_id"]): "viewer" for doc in docs}
            _db_users_loaded_at = time.monotonic()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ACCESS_USERS_LOAD_ERROR kind=%s", type(exc).__name__)
    return _db_users


async def _trial_end(email: str) -> float | None:
    cached = _trial_cache.get(email)
    if cached and time.monotonic() - cached[1] < USER_CACHE_SECONDS:
        return cached[0]
    try:
        doc = await _collection("access_trials").find_one({"_id": email})
    except Exception as exc:  # noqa: BLE001
        logger.warning("ACCESS_TRIAL_LOAD_ERROR kind=%s", type(exc).__name__)
        return cached[0] if cached else None
    ends_at = float(doc["ends_at"]) if doc and doc.get("ends_at") is not None else None
    _trial_cache[email] = (ends_at, time.monotonic())
    return ends_at


async def account_for(email: str) -> dict[str, Any] | None:
    """Who this email is: admin, viewer (approved), trial or expired. None = unknown email."""
    email = normalize_email(email)
    if email in admin_emails():
        return {"role": "admin", "trial_ends_at": None}
    if email in _email_set("ALLOWED_EMAILS") or (await _load_db_users()).get(email):
        return {"role": "viewer", "trial_ends_at": None}
    ends_at = await _trial_end(email)
    if ends_at is None:
        return None
    return {"role": "trial" if ends_at > time.time() else "expired", "trial_ends_at": ends_at}


async def role_for(email: str) -> str | None:
    account = await account_for(email)
    return account["role"] if account else None


async def _start_trial(email: str) -> float:
    now = time.time()
    ends_at = now + trial_days() * 86400
    await _collection("access_trials").replace_one({"_id": email}, {"_id": email, "started_at": now, "ends_at": ends_at}, upsert=True)
    _trial_cache[email] = (ends_at, time.monotonic())
    logger.info("ACCESS_TRIAL_STARTED days=%s", trial_days())
    return ends_at


# ---------------------------------------------------------------------------- email
def _send_mail_sync(to_address: str, subject: str, body: str) -> None:
    username = _env("SMTP_USERNAME")
    password = _env("SMTP_PASSWORD").replace(" ", "")
    host = _env("SMTP_HOST", "smtp.gmail.com")
    port = int(_env("SMTP_PORT", "587") or 587)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _env("SMTP_FROM") or username
    message["To"] = to_address
    message.set_content(body)
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


async def _send_mail(to_address: str, subject: str, body: str) -> bool:
    try:
        await asyncio.to_thread(_send_mail_sync, to_address, subject, body)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("ACCESS_EMAIL_ERROR kind=%s", type(exc).__name__)
        return False


# ---------------------------------------------------------------------------- sign-in codes
async def send_code(email: str) -> None:
    if not sign_in_configured():
        raise HTTPException(status_code=503, detail="Email sign-in isn't set up on the server yet.")
    email = normalize_email(email)
    if not valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    role = await role_for(email)
    if role is None and not signups_open():
        raise HTTPException(status_code=403, detail="This email doesn't have access yet. You can request it below.")
    now = time.time()
    if role is None:
        while _signup_codes and now - _signup_codes[0] > 3600:
            _signup_codes.popleft()
        if len(_signup_codes) >= _signup_code_cap():
            raise HTTPException(status_code=429, detail="Sign-ups are busy right now. Try again in a few minutes.")
    codes = _collection("access_codes")
    existing = await codes.find_one({"_id": email}) or {}
    recent = [stamp for stamp in existing.get("sends", []) if now - stamp < 3600]
    if recent and now - max(recent) < RESEND_COOLDOWN_SECONDS:
        wait = int(RESEND_COOLDOWN_SECONDS - (now - max(recent))) + 1
        raise HTTPException(status_code=429, detail=f"A code was just sent. Try again in {wait} seconds.")
    if len(recent) >= MAX_SENDS_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many codes requested. Try again in an hour.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    sent = await _send_mail(
        email,
        f"{code} is your EdgeDesk sign-in code",
        f"Your sign-in code is {code}\n\nIt expires in 10 minutes and can be used once.\n"
        "If you did not try to sign in, you can ignore this email.\n",
    )
    if not sent:
        raise HTTPException(status_code=502, detail="The code email couldn't be sent. Try again shortly.")
    if role is None:
        _signup_codes.append(now)
    await codes.replace_one(
        {"_id": email},
        {"_id": email, "code_hash": _code_hash(email, code), "expires_at": now + CODE_TTL_SECONDS, "attempts": 0, "sends": recent + [now]},
        upsert=True,
    )
    logger.info("ACCESS_CODE_SENT")


async def verify_code(email: str, code: str) -> dict[str, str]:
    email = normalize_email(email)
    code = re.sub(r"\D", "", code or "")
    if not sign_in_configured():
        raise HTTPException(status_code=503, detail="Email sign-in isn't set up on the server yet.")
    role = await role_for(email)
    if role is None and not signups_open():
        raise HTTPException(status_code=403, detail="This email doesn't have access yet. You can request it below.")
    codes = _collection("access_codes")
    record = await codes.find_one({"_id": email})
    now = time.time()
    if not record or not record.get("code_hash") or record.get("expires_at", 0) < now:
        raise HTTPException(status_code=400, detail="That code has expired. Request a new one.")
    if record.get("attempts", 0) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many wrong codes. Request a new one.")
    if len(code) != 6 or not hmac.compare_digest(record["code_hash"], _code_hash(email, code)):
        await codes.update_one({"_id": email}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400, detail="That code isn't right. Check the email and try again.")
    await codes.update_one({"_id": email}, {"$unset": {"code_hash": "", "expires_at": ""}, "$set": {"attempts": 0}})
    if role is None:
        await _start_trial(email)
    account = await account_for(email) or {"role": "trial", "trial_ends_at": None}
    logger.info("ACCESS_SIGNED_IN role=%s", account["role"])
    return {"email": email, "role": account["role"], "trial_ends_at": account["trial_ends_at"]}


# ---------------------------------------------------------------------------- access requests
async def request_access(email: str, name: str | None, note: str | None) -> dict[str, str]:
    if not sign_in_configured():
        raise HTTPException(status_code=503, detail="Access requests aren't set up on the server yet.")
    email = normalize_email(email)
    if not valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if await role_for(email) in {"admin", "viewer", "trial"}:
        return {"status": "approved"}
    requests_col = _collection("access_requests")
    if await requests_col.find_one({"_id": email}):
        return {"status": "pending"}
    now = time.time()
    if await requests_col.count_documents({"created_at": {"$gt": now - 3600}}) >= MAX_NEW_REQUESTS_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many requests right now. Try again in an hour.")
    clean_name, clean_note = _clean_text(name, 80), _clean_text(note, 300)
    await requests_col.replace_one(
        {"_id": email}, {"_id": email, "name": clean_name, "note": clean_note, "created_at": now}, upsert=True
    )
    logger.info("ACCESS_REQUESTED")
    body = (
        f"{email} asked for access to EdgeDesk.\n\n"
        f"Name: {clean_name or '(not given)'}\nNote: {clean_note or '(none)'}\n\n"
        f"Approve or decline it from the Access button at the bottom of the dashboard:\n{app_url()}\n"
    )
    for owner in sorted(admin_emails()):
        await _send_mail(owner, f"Access request from {email}", body)
    return {"status": "pending"}


async def list_requests() -> list[dict[str, Any]]:
    docs = await _collection("access_requests").find({}).sort("created_at", 1).to_list(500)
    return [{"email": d["_id"], "name": d.get("name", ""), "note": d.get("note", ""), "created_at": d.get("created_at")} for d in docs]


async def approve(email: str, owner: str | None) -> dict[str, Any]:
    email = normalize_email(email)
    if not valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    await _collection("access_users").replace_one(
        {"_id": email}, {"_id": email, "approved_at": time.time(), "approved_by": owner or ""}, upsert=True
    )
    await _collection("access_requests").delete_one({"_id": email})
    _db_users[email] = "viewer"
    emailed = await _send_mail(
        email,
        "You now have access to EdgeDesk",
        f"Your access request was approved.\n\nSign in at {app_url()} with this email address. "
        "You'll get a 6-digit code each time you sign in.\n",
    )
    logger.info("ACCESS_APPROVED emailed=%s", emailed)
    return {"email": email, "approved": True, "emailed": emailed}


async def decline(email: str) -> dict[str, Any]:
    email = normalize_email(email)
    await _collection("access_requests").delete_one({"_id": email})
    logger.info("ACCESS_DECLINED")
    return {"email": email, "declined": True}


async def list_users() -> list[dict[str, str]]:
    users: dict[str, dict[str, str]] = {}
    for email in sorted(admin_emails()):
        users[email] = {"email": email, "role": "admin", "source": "owner"}
    for email in sorted(_email_set("ALLOWED_EMAILS")):
        users.setdefault(email, {"email": email, "role": "viewer", "source": "render"})
    for email in sorted(await _load_db_users(force=True)):
        users.setdefault(email, {"email": email, "role": "viewer", "source": "approved"})
    now = time.time()
    trials = await _collection("access_trials").find({}).sort("started_at", -1).to_list(2000)
    for doc in trials:
        email = normalize_email(doc["_id"])
        ends_at = float(doc.get("ends_at") or 0)
        users.setdefault(email, {"email": email, "role": "trial" if ends_at > now else "expired", "source": "trial", "trial_ends_at": ends_at})
    return list(users.values())


async def remove_user(email: str) -> dict[str, Any]:
    email = normalize_email(email)
    if email in admin_emails() or email in _email_set("ALLOWED_EMAILS"):
        raise HTTPException(status_code=400, detail="This email is set in Render. Remove it there instead.")
    await _collection("access_users").delete_one({"_id": email})
    _db_users.pop(email, None)
    if await _collection("access_trials").find_one({"_id": email}):
        ended = time.time()
        await _collection("access_trials").update_one({"_id": email}, {"$set": {"ends_at": ended}})
        _trial_cache[email] = (ended, time.monotonic())
    logger.info("ACCESS_REMOVED")
    return {"email": email, "removed": True}


# ---------------------------------------------------------------------------- sessions
def issue_session(email: str, role: str) -> tuple[str, int]:
    max_age = _session_days() * 86400
    now = int(time.time())
    token = jwt.encode({"sub": email, "role": role, "iat": now, "exp": now + max_age}, _secret(), algorithm="HS256")
    return token, max_age


async def read_session(token: str | None) -> dict[str, str] | None:
    if not token or len(_secret()) < 16:
        return None
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    email = normalize_email(str(claims.get("sub", "")))
    account = await account_for(email)  # re-checked on every request: removing someone revokes access
    if account is None:
        return None
    return {"email": email, "role": account["role"], "trial_ends_at": account["trial_ends_at"]}


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
    user = await read_session(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if user["role"] == "expired":
        raise HTTPException(status_code=402, detail="Your free trial has ended.")
    return user


async def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only the owner can do this.")
    return user
