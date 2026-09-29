from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from lib import access


router = APIRouter(prefix="/access", tags=["access"])


class CodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class VerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=6, max_length=12)


@router.get("/me")
async def who_am_i(request: Request) -> dict:
    if not access.auth_required():
        return {"auth_required": False, "email": None, "role": "admin"}
    user = access.read_session(request.cookies.get(access.COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return {"auth_required": True, **user}


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
