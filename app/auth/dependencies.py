import logging
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.auth.neon_auth import verify_token
from app.auth.roles import ROLE_HIERARCHY
from app.db.neon import get_db

logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_current_user(token: str = Depends(oauth2_scheme), db=Depends(get_db)):
    try:
        payload = await verify_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    neon_auth_id = payload.get("sub")
    email = payload.get("email", "")
    name = payload.get("name", "")

    if not neon_auth_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing sub",
        )

    row = await db.fetchrow(
        "SELECT * FROM users WHERE neon_auth_id = $1", neon_auth_id
    )

    if row:
        user = dict(row)
        if not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account deactivated",
            )
        await db.execute(
            "UPDATE users SET last_login_at = $1, email = $2 WHERE id = $3",
            datetime.now(timezone.utc), email, user["id"],
        )
        return user

    role = "superadmin" if email == settings.first_superadmin_email else "user"

    new_id = uuid4()
    await db.execute(
        """INSERT INTO users (id, neon_auth_id, email, full_name, role, is_active, is_email_verified)
           VALUES ($1, $2, $3, $4, $5, true, true)""",
        new_id, neon_auth_id, email, name, role,
    )

    row = await db.fetchrow("SELECT * FROM users WHERE id = $1", new_id)
    return dict(row)


async def get_admin_user(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ("superadmin", "admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_superadmin_user(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin access required",
        )
    return current_user


def require_role(required_role: str) -> Callable:
    async def _role_checker(current_user: dict = Depends(get_current_user)):
        if ROLE_HIERARCHY.get(current_user["role"], 0) < ROLE_HIERARCHY.get(required_role, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required_role}' or higher required",
            )
        return current_user
    return _role_checker
