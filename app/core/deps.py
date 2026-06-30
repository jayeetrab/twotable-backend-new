from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.security import decode_token
from app.db import mongo
from app.models.user import UserRole

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """Resolve the authenticated user document from the access token."""
    token = credentials.credentials
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    db = mongo.get_db()
    # Token subject is an email (password users) or a phone (OTP users).
    sub = payload["sub"]
    user = await db[mongo.USERS].find_one({"$or": [{"email": sub}, {"phone": sub}]})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_current_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != UserRole.admin.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only")
    return user


async def get_current_venue(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != UserRole.venue.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Venues only")
    return user
