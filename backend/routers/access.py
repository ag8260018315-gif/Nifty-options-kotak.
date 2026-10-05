from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from lib import access, premium


router = APIRouter(prefix="/access", tags=["access"])


class CodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class VerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=6, max_length=12)


class AccessRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)


class EmailBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class PremiumGrant(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    days: int = Field(default=30, ge=1, le=premium.MAX_DAYS)


# ------------------------------------------------------------------ public
@router.get("/me")
async def who_am_i(request: Request) -> dict:
    if not access.auth_required():
        return {"auth_required": False, "email": None, "role": "admin", "premium": True, "premium_until": None}
    user = await access.read_session(request.cookies.get(access.COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return {"auth_required": True, **user, **await premium.status_for(user)}


@router.post("/request-code")
async def request_code(body: CodeRequest) -> dict:
    await access.send_code(body.email)
    return {"sent": True, "expires_in": access.CODE_TTL_SECONDS}


@router.post("/verify")
async def verify(body: VerifyRequest, response: Response) -> dict:
    user = await access.verify_code(body.email, body.code)
    token, max_age = access.issue_session(user["email"], user["role"])
    response.set_cookie(value=token, **access.cookie_settings(max_age))
    return {"auth_required": access.auth_required(), **user}


@router.post("/logout")
async def logout(response: Response) -> dict:
    settings = access.cookie_settings(0)
    response.delete_cookie(key=settings["key"], path=settings["path"], secure=settings["secure"], httponly=True, samesite="strict")
    return {"signed_out": True}


@router.post("/request")
async def request_access(body: AccessRequest) -> dict:
    return await access.request_access(body.email, body.name, body.note)


# ------------------------------------------------------------------ owner only
@router.get("/admin/requests")
async def pending_requests(owner: dict[str, Any] = Depends(access.require_admin)) -> list[dict]:
    return await access.list_requests()


@router.get("/admin/users")
async def approved_users(owner: dict[str, Any] = Depends(access.require_admin)) -> list[dict]:
    return await access.list_users()


@router.post("/admin/approve")
async def approve_request(body: EmailBody, owner: dict[str, Any] = Depends(access.require_admin)) -> dict:
    return await access.approve(body.email, owner.get("email"))


@router.post("/admin/decline")
async def decline_request(body: EmailBody, owner: dict[str, Any] = Depends(access.require_admin)) -> dict:
    return await access.decline(body.email)


@router.post("/admin/remove")
async def remove_user(body: EmailBody, owner: dict[str, Any] = Depends(access.require_admin)) -> dict:
    return await access.remove_user(body.email)


# ------------------------------------------------------------------ premium (owner only)
@router.get("/admin/premium")
async def premium_holders(owner: dict[str, Any] = Depends(access.require_admin)) -> list[dict]:
    return await premium.list_premium()


@router.post("/admin/premium")
async def grant_premium(body: PremiumGrant, owner: dict[str, Any] = Depends(access.require_admin)) -> dict:
    return await premium.grant(body.email, body.days, owner.get("email"))


@router.post("/admin/premium/revoke")
async def revoke_premium(body: EmailBody, owner: dict[str, Any] = Depends(access.require_admin)) -> dict:
    return await premium.revoke(body.email)


class MoveData(BaseModel):
    old: str = Field(min_length=3, max_length=320)
    new: str = Field(min_length=3, max_length=320)
    apply: bool = False


@router.post("/admin/move-data")
async def move_data(body: MoveData, owner: dict[str, Any] = Depends(access.require_admin)) -> dict:
    """Owner only: move one email's saved watchlists, layouts, alerts, Exchange items and subscription to another email. Previews unless apply is true."""
    from lib.db import db
    from lib.owner_move import move_owner_data

    old, new = access.normalize_email(body.old), access.normalize_email(body.new)
    if not access.valid_email(old) or not access.valid_email(new) or old == new:
        raise HTTPException(status_code=422, detail="Enter two different, valid email addresses.")
    return {"moved": body.apply, "report": await move_owner_data(db, old, new, apply=body.apply)}


@router.post("/premium-request")
async def request_premium(user: dict[str, Any] = Depends(access.require_user)) -> dict:
    if not user.get("email"):
        raise HTTPException(status_code=400, detail="Sign in first.")
    return await premium.request_premium(user["email"])
