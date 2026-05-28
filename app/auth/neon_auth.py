import logging
from typing import Optional

from app.core.security import verify_token as _verify_token

logger = logging.getLogger(__name__)


async def verify_token(token: str) -> dict:
    """Verify a Stack Auth JWT token and return the decoded payload.

    Returns dict with at minimum: sub (neon_auth_id), email, name.
    Raises ValueError if token is invalid or expired.
    """
    payload = await _verify_token(token)
    return {
        "sub": payload.get("sub"),
        "email": payload.get("email", ""),
        "name": payload.get("name", payload.get("nickname", "")),
    }
