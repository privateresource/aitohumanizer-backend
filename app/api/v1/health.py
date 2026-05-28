import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
import app.db.neon

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    db: str
    version: str


@router.get("", response_model=HealthResponse)
async def health_check():
    db_status = "connected"
    try:
        p = app.db.neon.pool
        if p:
            async with p.acquire() as conn:
                await conn.execute("SELECT 1")
        else:
            db_status = "not_initialized"
    except Exception as e:
        logger.warning("Health check DB error: %s", e)
        db_status = "error"

    return HealthResponse(
        status="ok" if db_status == "connected" else "degraded",
        db=db_status,
        version="1.0.0",
    )


@router.get("/llm-status")
async def llm_status():
    from app.api.deps import _get_session_factory
    from app.llm.router import get_router, get_providers
    from sqlalchemy import text

    router = get_router()
    providers = get_providers()
    db_providers = 0
    db_keys = 0
    db_error = None
    try:
        factory = _get_session_factory()
        async with factory() as s:
            r = await s.execute(text("SELECT COUNT(*) FROM llm_providers"))
            db_providers = r.scalar_one()
            r = await s.execute(text("SELECT COUNT(*) FROM llm_provider_keys"))
            db_keys = r.scalar_one()
    except Exception as e:
        db_error = str(e)

    return {
        "router_initialized": router is not None,
        "in_memory_providers": len(providers),
        "in_memory_ids": list(providers.keys()),
        "db_provider_count": db_providers,
        "db_key_count": db_keys,
        "db_error": db_error,
    }
