import uuid
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings
from app.core.security import verify_token
from app.core.exceptions import UnauthorizedException, ForbiddenException
from app.core.constants import ROLE_HIERARCHY
from app.db.repositories.user_repo import UserRepository
from app.db.repositories.subscription_repo import SubscriptionRepository
from app.db.repositories.plan_repo import PlanRepository
from app.db.repositories.word_usage_repo import WordUsageRepository
from app.db.repositories.humanize_repo import HumanizeRepository
from app.db.repositories.admin_repo import AdminRepository
from app.db.models.user import User

security = HTTPBearer()

_engine = None
_session_factory = None


def _clean_async_url(url: str) -> str:
    from urllib.parse import urlparse, urlunparse
    async_url = url.replace("postgresql://", "postgresql+asyncpg://")
    parsed = urlparse(async_url)
    query = "&".join(
        p for p in parsed.query.split("&") if p and not p.startswith("sslmode=")
    )
    return urlunparse(parsed._replace(query=query))


def _get_session_factory():
    global _engine, _session_factory
    if _session_factory is None:
        async_url = _clean_async_url(settings.database_url)
        _engine = create_async_engine(
            async_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


async def get_db_session():
    factory = _get_session_factory()
    async with factory() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    try:
        payload = await verify_token(credentials.credentials)
    except ValueError as e:
        raise UnauthorizedException(message=str(e))

    neon_auth_id = payload.get("sub")
    if not neon_auth_id:
        raise UnauthorizedException(message="Invalid token: missing sub")

    email = payload.get("email", "")
    user_repo = UserRepository(session)
    user = await user_repo.get_by_neon_auth_id(neon_auth_id)

    if not user:
        role = "superadmin" if email.lower() == settings.first_superadmin_email.lower() else "user"
        user = User(
            neon_auth_id=neon_auth_id,
            email=email,
            full_name=payload.get("name", ""),
            role=role,
            is_active=True,
            is_email_verified=payload.get("email_verified", False),
            avatar_url=payload.get("picture", None),
        )
        user = await user_repo.create(user)

    if not user.is_active:
        raise ForbiddenException(message="Account is suspended")

    return user


async def get_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    required_level = ROLE_HIERARCHY.get("manager", 60)
    user_level = ROLE_HIERARCHY.get(current_user.role, 0)
    if user_level < required_level:
        raise ForbiddenException(
            message="Admin access required",
            detail={"required_role": "manager or higher", "your_role": current_user.role},
        )
    return current_user


async def get_superadmin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != "superadmin":
        raise ForbiddenException(message="Superadmin access required")
    return current_user
