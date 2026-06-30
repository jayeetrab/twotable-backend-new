from __future__ import annotations

"""
Spotify OAuth 2.0 Authorization Code Flow

Endpoints:
  GET /api/v1/auth/spotify/connect-url  — returns Spotify auth URL to frontend
  GET /api/v1/auth/spotify/connect      — direct redirect (browser only)
  GET /api/v1/auth/spotify/callback     — Spotify redirects here with ?code=&state=

Flow:
  1. User (with JWT) calls /connect-url
  2. We encode their user_id into a signed state token (CSRF protection)
  3. Frontend opens the returned URL in the browser
  4. User approves on Spotify
  5. Spotify redirects to /callback with code + state
  6. We verify state, extract user_id
  7. We exchange code for access_token + refresh_token
  8. We save tokens to user_social_connections
  9. We run the Spotify signal pipeline
  10. We re-embed the user
  11. We redirect user back to frontend
"""

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.user_social_connection import SocialPlatform, UserSocialConnection
from app.services.social.pipeline import run_spotify_pipeline
from app.services.user_embeddings import upsert_user_embedding

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["spotify oauth"])

SPOTIFY_AUTH_URL  = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"

# Scopes — read top artists, tracks, audio features, basic profile
SPOTIFY_SCOPES = "user-top-read user-read-recently-played user-read-private"


# ── State helpers (CSRF protection) ──────────────────────────────────────────

def _sign_state(user_id: int) -> str:
    """
    Encode user_id into a signed state string sent to Spotify.
    Spotify echoes it back unchanged — we verify on return.
    """
    payload = json.dumps({"user_id": user_id}).encode()
    sig = hmac.new(
        settings.JWT_SECRET_KEY.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(payload).decode() + "." + sig


def _verify_state(state: str) -> int:
    """
    Verify state signature and return user_id.
    Raises HTTPException 400 if tampered or malformed.
    """
    try:
        encoded, sig = state.rsplit(".", 1)
        payload = base64.urlsafe_b64decode(encoded.encode())
        expected = hmac.new(
            settings.JWT_SECRET_KEY.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("Signature mismatch")
        return int(json.loads(payload)["user_id"])
    except Exception as exc:
        logger.warning("Invalid Spotify OAuth state: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth state. Please try connecting again.",
        )


def _build_auth_url(user_id: int) -> str:
    """Build the full Spotify authorization URL with signed state."""
    params = {
        "client_id":     settings.SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  settings.SPOTIFY_REDIRECT_URI,
        "scope":         SPOTIFY_SCOPES,
        "state":         _sign_state(user_id),
        "show_dialog":   "false",
    }
    return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/spotify/connect-url")
async def spotify_connect_url(
    current_user: User = Depends(get_current_user),
):
    """
    Returns the Spotify auth URL as JSON.
    Frontend receives this and does: window.location.href = url

    Preferred approach — works with Authorization header / JWT.
    """
    if not settings.SPOTIFY_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration is not configured. Set SPOTIFY_CLIENT_ID in .env",
        )
    url = _build_auth_url(current_user.id)
    logger.info("Spotify connect-url generated for user_id=%d", current_user.id)
    return {"url": url}


@router.get("/spotify/connect")
async def spotify_connect(
    current_user: User = Depends(get_current_user),
):
    """
    Direct browser redirect to Spotify.
    Only works if the JWT is in a cookie — not via Authorization header.
    Use /connect-url instead for React apps.
    """
    if not settings.SPOTIFY_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="Spotify integration is not configured. Set SPOTIFY_CLIENT_ID in .env",
        )
    url = _build_auth_url(current_user.id)
    logger.info("Spotify connect redirect for user_id=%d", current_user.id)
    return RedirectResponse(url=url)


@router.get("/spotify/callback")
async def spotify_callback(
    code:  str = Query(..., description="Authorization code from Spotify"),
    state: str = Query(..., description="Signed state token we sent"),
    error: str = Query(None, description="Set by Spotify if user denied access"),
    db: AsyncSession = Depends(get_db),
):
    """
    Spotify redirects here after user approves/denies.
    No JWT needed — user_id is recovered from signed state.

    Success → redirects to FRONTEND_REDIRECT_URL?platform=spotify&status=success&signals=N
    Denied  → redirects to FRONTEND_REDIRECT_URL?platform=spotify&status=denied
    Error   → redirects to FRONTEND_REDIRECT_URL?platform=spotify&status=error&reason=...
    """
    frontend_base = settings.FRONTEND_REDIRECT_URL

    # ── User denied on Spotify ────────────────────────────────────────────────
    if error:
        logger.warning("Spotify OAuth denied by user: %s", error)
        return RedirectResponse(
            url=f"{frontend_base}?platform=spotify&status=denied&reason={error}"
        )

    # ── Verify state → get user_id ────────────────────────────────────────────
    user_id = _verify_state(state)

    # ── Exchange code for tokens ──────────────────────────────────────────────
    credentials = base64.b64encode(
        f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                SPOTIFY_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type":  "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type":   "authorization_code",
                    "code":          code,
                    "redirect_uri":  settings.SPOTIFY_REDIRECT_URI,
                },
            )

        if token_resp.status_code != 200:
            logger.error(
                "Spotify token exchange failed %d: %s",
                token_resp.status_code, token_resp.text,
            )
            return RedirectResponse(
                url=f"{frontend_base}?platform=spotify&status=error&reason=token_exchange_failed"
            )

        token_data = token_resp.json()

    except httpx.RequestError as exc:
        logger.error("Spotify token request network error: %s", exc)
        return RedirectResponse(
            url=f"{frontend_base}?platform=spotify&status=error&reason=network_error"
        )

    access_token      = token_data["access_token"]
    refresh_token     = token_data.get("refresh_token")
    expires_in        = token_data.get("expires_in", 3600)
    token_expires_at  = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # ── Fetch Spotify profile ─────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            profile_resp = await client.get(
                "https://api.spotify.com/v1/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        spotify_profile = profile_resp.json() if profile_resp.status_code == 200 else {}
    except Exception as exc:
        logger.warning("Could not fetch Spotify profile: %s", exc)
        spotify_profile = {}

    platform_user_id  = spotify_profile.get("id", "")
    platform_username = (
        spotify_profile.get("display_name")
        or spotify_profile.get("id", "")
    )

    # ── Upsert UserSocialConnection ───────────────────────────────────────────
    result = await db.execute(
        select(UserSocialConnection).where(
            UserSocialConnection.user_id == user_id,
            UserSocialConnection.platform == SocialPlatform.spotify,
        )
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.access_token       = access_token
        conn.refresh_token      = refresh_token
        conn.token_expires_at   = token_expires_at
        conn.platform_user_id   = platform_user_id
        conn.platform_username  = platform_username
        conn.is_active          = True
        conn.connected_at       = datetime.now(timezone.utc)
    else:
        conn = UserSocialConnection(
            user_id=user_id,
            platform=SocialPlatform.spotify,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
            platform_user_id=platform_user_id,
            platform_username=platform_username,
        )
        db.add(conn)

    await db.commit()
    logger.info(
        "Spotify tokens saved for user_id=%d username=%s",
        user_id, platform_username,
    )

    # ── Run signal pipeline ───────────────────────────────────────────────────
    signals_saved = 0
    try:
        pipeline_result = await run_spotify_pipeline(
            user_id=user_id,
            access_token=access_token,
            db=db,
        )
        signals_saved = pipeline_result.get("signals_saved", 0)
        logger.info(
            "Spotify pipeline complete: %d signals saved for user_id=%d",
            signals_saved, user_id,
        )
    except Exception as exc:
        logger.error("Spotify pipeline failed for user_id=%d: %s", user_id, exc)

    # ── Refresh user embedding ────────────────────────────────────────────────
    try:
        await upsert_user_embedding(db=db, user_id=user_id)
        logger.info("User embedding refreshed for user_id=%d", user_id)
    except Exception as exc:
        logger.warning("Embedding refresh failed for user_id=%d: %s", user_id, exc)

    # ── Redirect to frontend ──────────────────────────────────────────────────
    return RedirectResponse(
        url=f"{frontend_base}?platform=spotify&status=success&signals={signals_saved}"
    )


# ── Token refresh utility ─────────────────────────────────────────────────────

async def refresh_spotify_token(
    db: AsyncSession,
    user_id: int,
) -> str | None:
    """
    Exchange the stored refresh_token for a new access_token.
    Updates the DB row in place and returns the new access_token.
    Returns None if no refresh token exists or the refresh fails.

    Call this whenever a Spotify API call returns 401.
    """
    result = await db.execute(
        select(UserSocialConnection).where(
            UserSocialConnection.user_id == user_id,
            UserSocialConnection.platform == SocialPlatform.spotify,
            UserSocialConnection.is_active == True,  # noqa: E712
        )
    )
    conn = result.scalar_one_or_none()

    if not conn or not conn.refresh_token:
        logger.warning(
            "No active Spotify connection or refresh token for user_id=%d", user_id
        )
        return None

    credentials = base64.b64encode(
        f"{settings.SPOTIFY_CLIENT_ID}:{settings.SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                SPOTIFY_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type":  "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token":  conn.refresh_token,
                },
            )

        if resp.status_code != 200:
            logger.error(
                "Spotify token refresh failed %d: %s",
                resp.status_code, resp.text,
            )
            return None

        data = resp.json()
        conn.access_token    = data["access_token"]
        conn.token_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600))
        )
        # Spotify sometimes rotates the refresh token
        if "refresh_token" in data:
            conn.refresh_token = data["refresh_token"]

        await db.commit()
        logger.info("Spotify token refreshed for user_id=%d", user_id)
        return conn.access_token

    except Exception as exc:
        logger.error("Spotify token refresh error for user_id=%d: %s", user_id, exc)
        return None
