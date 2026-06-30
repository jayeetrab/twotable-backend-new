import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.security import (
    create_access_token, create_refresh_token,
    decode_token, hash_password, verify_password,
)
from app.db import mongo
from app.models.user import UserRole
from app.schemas.auth import (
    LoginRequest, RefreshRequest, RegisterRequest,
    TokenResponse, UserRead, UserUpdate,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _normalize_phone(raw: str) -> str:
    """Keep a leading + and digits only, so '+44 7700 900123' == '+447700900123'."""
    s = raw.strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    return ("+" if plus else "") + digits


# ── Phone + OTP auth (dev OTP until SMS is wired) ─────────────────────────────

class PhoneStartRequest(BaseModel):
    phone: str


class PhoneVerifyRequest(BaseModel):
    phone: str
    code: str


# Per-number bypass codes (digits-suffix match). Lets specific test numbers sign in
# with a fixed code even if the universal dev code changes.
_BYPASS_CODES = {
    "7438153933": "700175",
}


def _bypass_ok(phone: str, code: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    return any(digits.endswith(num) and code.strip() == c for num, c in _BYPASS_CODES.items())


@router.post("/phone/start")
async def phone_start(payload: PhoneStartRequest):
    """Begin phone sign-in. In dev no SMS is sent — any number accepts DEV_OTP_CODE."""
    phone = _normalize_phone(payload.phone)
    if len(re.sub(r"\D", "", phone)) < 6:
        raise HTTPException(status_code=422, detail="Invalid phone number")
    resp = {"sent": True, "phone": phone}
    if settings.APP_ENV != "production":
        resp["dev_code"] = settings.DEV_OTP_CODE
    return resp


@router.post("/phone/verify", response_model=TokenResponse)
async def phone_verify(payload: PhoneVerifyRequest):
    """Verify the OTP and create the account on first use. Returns JWT tokens."""
    phone = _normalize_phone(payload.phone)
    if payload.code.strip() != settings.DEV_OTP_CODE and not _bypass_ok(phone, payload.code):
        raise HTTPException(status_code=401, detail="Invalid verification code")

    db = mongo.get_db()
    user = await db[mongo.USERS].find_one({"phone": phone})
    if user is None:
        now = datetime.now(timezone.utc)
        user = {
            "_id": await mongo.next_id("users"),
            "email": None,
            "phone": phone,
            "hashed_password": None,
            "role": UserRole.dater.value,
            "is_active": True,
            "full_name": None,
            "preferred_mood": None,
            "preferred_budget": None,
            "preferred_stage": None,
            "dietary_requirements": None,
            "created_at": now,
            "updated_at": now,
        }
        await db[mongo.USERS].insert_one(user)

    return TokenResponse(
        access_token=create_access_token(phone, user["role"]),
        refresh_token=create_refresh_token(phone, user["role"]),
    )


def _user_read(doc: dict) -> UserRead:
    return UserRead(
        id=doc["_id"],
        email=doc.get("email"),
        phone=doc.get("phone"),
        role=doc.get("role", UserRole.dater.value),
        full_name=doc.get("full_name"),
        is_active=doc.get("is_active", True),
    )


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest):
    db = mongo.get_db()
    now = datetime.now(timezone.utc)
    role = payload.role.value if isinstance(payload.role, UserRole) else payload.role
    doc = {
        "_id": await mongo.next_id("users"),
        "email": payload.email,
        "hashed_password": hash_password(payload.password),
        "role": role,
        "is_active": True,
        "full_name": payload.full_name,
        "preferred_mood": None,
        "preferred_budget": None,
        "preferred_stage": None,
        "dietary_requirements": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db[mongo.USERS].insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    return _user_read(doc)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    db = mongo.get_db()
    user = await db[mongo.USERS].find_one({"email": payload.email})
    if not user or not verify_password(payload.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    return TokenResponse(
        access_token=create_access_token(user["email"], user["role"]),
        refresh_token=create_refresh_token(user["email"], user["role"]),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    db = mongo.get_db()
    data = decode_token(payload.refresh_token)
    if not data or data.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = await db[mongo.USERS].find_one({"email": data["sub"]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return TokenResponse(
        access_token=create_access_token(user["email"], user["role"]),
        refresh_token=create_refresh_token(user["email"], user["role"]),
    )


@router.get("/me", response_model=UserRead)
async def me(user: dict = Depends(get_current_user)):
    return _user_read(user)


@router.patch("/me", response_model=UserRead)
async def update_me(
    payload: UserUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Update the current user's base fields. Only provided fields are updated."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    updates["updated_at"] = datetime.now(timezone.utc)
    db = mongo.get_db()
    doc = await db[mongo.USERS].find_one_and_update(
        {"_id": current_user["_id"]},
        {"$set": updates},
        return_document=True,
    )
    return _user_read(doc)
