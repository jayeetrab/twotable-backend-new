"""
Selfie analysis for profile verification.

We can't do biometric identity matching without a paid KYC vendor, but we can run a
genuine automated quality/liveness-lite check server-side: the selfie must contain exactly
one clear, front-facing, reasonably large face. That blocks the obvious junk (no face,
group photos, tiny faces, screenshots of text) and is what earns the verified badge.

Uses OpenCV's Haar frontal-face cascade (ships with opencv-python-headless — light, no GPU).
Everything is graceful: if OpenCV isn't installed the caller falls back to manual review.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _CASCADE = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    _AVAILABLE = not _CASCADE.empty()
except Exception as exc:                                   # opencv missing / cascade unreadable
    logger.warning("Face analysis unavailable: %s", exc)
    _AVAILABLE = False


@dataclass
class FaceResult:
    ok: bool                 # True → passes the verification bar
    available: bool          # False → we couldn't analyse (no OpenCV) → manual review
    faces: int               # number of faces detected
    reason: Optional[str]    # user-facing explanation when not ok


def analyse_selfie(image_bytes: bytes) -> FaceResult:
    """Return whether a selfie passes the verification bar: exactly one clear, front-facing face."""
    if not _AVAILABLE:
        return FaceResult(ok=False, available=False, faces=0, reason=None)
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return FaceResult(False, True, 0, "That image couldn't be read. Please try again.")
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Face must be a meaningful fraction of the frame (a real selfie), not a tiny speck.
        min_side = max(80, int(min(h, w) * 0.15))
        faces = _CASCADE.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side))
        n = len(faces)
        if n == 0:
            return FaceResult(False, True, 0,
                              "We couldn't find a clear face. Face the camera in good light and try again.")
        if n > 1:
            return FaceResult(False, True, n,
                              "We found more than one face. Please take a solo selfie.")
        return FaceResult(True, True, 1, None)
    except Exception as exc:
        logger.warning("Selfie analysis error: %s", exc)
        return FaceResult(False, True, 0, "We couldn't analyse that photo. Please try again.")
