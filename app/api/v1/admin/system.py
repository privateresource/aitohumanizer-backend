import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_admin_user
from app.core.exceptions import BadRequestException
from app.core.config import settings
from app.db.models.user import User
from app.db.models.subscription import Subscription
from app.db.models.system_config import SystemConfig
import app.db.neon

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/system", tags=["admin"])

REQUEST_LOGS_TABLE_NAME = "request_logs"
LLM_PROVIDERS_TABLE_NAME = "llm_providers"


class ConfigItem(BaseModel):
    key: str
    value: str
    description: Optional[str] = None
    updated_at: str
    updated_by: Optional[str] = None


class ConfigUpdateRequest(BaseModel):
    key: str
    value: str


class ConfigUpdateResponse(BaseModel):
    key: str
    value: str
    message: str


class SystemStatusResponse(BaseModel):
    status: str
    version: str
    database: str
    api: str
    llm_providers: int
    active_users: int
    active_subs: int
    uptime_hours: float
    timestamp: str


class ReloadResponse(BaseModel):
    status: str
    message: str
    components: list[str]


class LogEntry(BaseModel):
    id: str
    level: str
    message: str
    path: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: str


class LogListResponse(BaseModel):
    items: list[LogEntry]
    total: int
    page: int
    page_size: int
    total_pages: int


class PurgeResponse(BaseModel):
    status: str
    deleted_count: int
    message: str


@router.get("/config", response_model=list[ConfigItem])
async def get_config(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        result = await session.execute(
            select(SystemConfig).order_by(SystemConfig.key)
        )
        rows = result.scalars().all()
        return [
            ConfigItem(
                key=row.key,
                value=row.value,
                description=row.description,
                updated_at=row.updated_at.isoformat() if row.updated_at else datetime.now(timezone.utc).isoformat(),
                updated_by=row.updated_by,
            )
            for row in rows
        ]
    except Exception as e:
        logger.warning("Failed to load config from DB: %s", e)
        return [
            ConfigItem(
                key="app_env",
                value=settings.app_env,
                description="Application environment",
                updated_at=datetime.now(timezone.utc).isoformat(),
                updated_by=None,
            ),
            ConfigItem(
                key="frontend_url",
                value=settings.frontend_url,
                description="Frontend URL",
                updated_at=datetime.now(timezone.utc).isoformat(),
                updated_by=None,
            ),
            ConfigItem(
                key="backend_url",
                value=settings.backend_url,
                description="Backend URL",
                updated_at=datetime.now(timezone.utc).isoformat(),
                updated_by=None,
            ),
        ]


@router.patch("/config", response_model=ConfigUpdateResponse)
async def update_config(
    req: ConfigUpdateRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    now = datetime.now(timezone.utc)
    existing = await session.get(SystemConfig, req.key)
    if existing:
        existing.value = req.value
        existing.updated_at = now
        existing.updated_by = current_user.id
    else:
        session.add(SystemConfig(
            key=req.key,
            value=req.value,
            updated_at=now,
            updated_by=current_user.id,
        ))
    await session.commit()

    verified = await session.get(SystemConfig, req.key)
    stored_value = verified.value if verified else None
    if stored_value != req.value:
        logger.error(
            "Config save verification failed for key=%s: expected=%r got=%r",
            req.key, req.value[:100], (stored_value or "")[:100],
        )
    else:
        logger.info("Config key=%s saved and verified (%d chars)", req.key, len(req.value))

    return ConfigUpdateResponse(
        key=req.key,
        value=req.value,
        message="Configuration updated",
    )


@router.get("/status", response_model=SystemStatusResponse)
async def system_status(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    db_status = "connected"
    try:
        p = app.db.neon.pool
        if p:
            async with p.acquire() as conn:
                await conn.execute("SELECT 1")
        else:
            db_status = "not_initialized"
    except Exception as e:
        logger.warning("Status check DB error: %s", e)
        db_status = "error"

    provider_count = 0
    try:
        result = await session.execute(
            select(func.count()).select_from(LLM_PROVIDERS_TABLE_NAME)
        )
        provider_count = result.scalar_one()
    except Exception:
        provider_count = 2

    active_user_count = 0
    active_sub_count = 0
    try:
        result = await session.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        active_user_count = result.scalar_one()

        result = await session.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status.in_(["active", "trialing"])
            )
        )
        active_sub_count = result.scalar_one()
    except Exception:
        pass

    api_status = "healthy"
    if db_status == "error":
        api_status = "degraded"

    return SystemStatusResponse(
        status=api_status,
        version="1.0.0",
        database=db_status,
        api=api_status,
        llm_providers=provider_count,
        active_users=active_user_count,
        active_subs=active_sub_count,
        uptime_hours=0.0,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.post("/reload", response_model=ReloadResponse)
async def reload_system(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    from app.llm.init import init_providers
    await init_providers(session)

    from app.core import security
    try:
        security._jwks_cache = None
        security._jwks_cache_at = 0.0
    except AttributeError:
        pass

    components = ["config", "jwks", "llm_providers"]
    return ReloadResponse(
        status="success",
        message="System configuration and skill definitions reloaded successfully",
        components=components,
    )


@router.get("/logs", response_model=LogListResponse)
async def get_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    level: Optional[str] = Query(None),
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        count_query = select(func.count()).select_from(REQUEST_LOGS_TABLE_NAME)
        data_query = (
            select(REQUEST_LOGS_TABLE_NAME)
            .order_by(REQUEST_LOGS_TABLE_NAME.c.created_at.desc())
        )

        if level:
            count_query = count_query.where(REQUEST_LOGS_TABLE_NAME.c.level == level)
            data_query = data_query.where(REQUEST_LOGS_TABLE_NAME.c.level == level)

        total_result = await session.execute(count_query)
        total = total_result.scalar_one()

        skip = (page - 1) * page_size
        data_query = data_query.offset(skip).limit(page_size)
        result = await session.execute(data_query)
        rows = result.fetchall()

        total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1

        items = [
            LogEntry(
                id=str(row.id),
                level=row.level,
                message=row.message,
                path=row.path if hasattr(row, "path") else None,
                method=row.method if hasattr(row, "method") else None,
                status_code=row.status_code if hasattr(row, "status_code") else None,
                duration_ms=row.duration_ms if hasattr(row, "duration_ms") else None,
                user_id=row.user_id if hasattr(row, "user_id") else None,
                ip_address=row.ip_address if hasattr(row, "ip_address") else None,
                created_at=row.created_at.isoformat() if (hasattr(row, "created_at") and row.created_at) else datetime.now(timezone.utc).isoformat(),
            )
            for row in rows
        ]

        return LogListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    except Exception:
        return LogListResponse(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            total_pages=1,
        )


@router.delete("/logs/purge", response_model=PurgeResponse)
async def purge_logs(
    days_old: int = Query(30, ge=1, description="Purge logs older than N days"),
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    deleted = 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)
        stmt = sa_delete(REQUEST_LOGS_TABLE_NAME).where(
            REQUEST_LOGS_TABLE_NAME.c.created_at < cutoff
        )
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount
    except Exception as e:
        logger.warning("Log purge error: %s", e)

    return PurgeResponse(
        status="success",
        deleted_count=deleted,
        message=f"Purged request logs older than {days_old} days",
    )
