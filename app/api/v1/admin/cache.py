import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.api.deps import get_db_session, get_admin_user
from app.cache import cache as cache_store
from app.cache.invalidation import (
    invalidate_all,
    invalidate_system_config,
    invalidate_llm_providers,
    invalidate_lt_servers,
)
from app.db.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/cache", tags=["admin"])


@router.get("/stats")
async def get_cache_stats(current_user: User = Depends(get_admin_user)):
    s = cache_store.stats()
    return {
        "total_keys": s["total_keys"],
        "is_loaded": s["is_loaded"],
        "keys": s["keys"],
        "last_refreshed": None,
    }


@router.post("/refresh")
async def refresh_cache(current_user: User = Depends(get_admin_user), session: AsyncSession = Depends(get_db_session)):
    await invalidate_all()
    await cache_store.load_all_plans()
    s = cache_store.stats()
    return {
        "status": "ok",
        "total_keys": s["total_keys"],
        "is_loaded": s["is_loaded"],
    }


@router.post("/refresh/plans")
async def refresh_plans(current_user: User = Depends(get_admin_user)):
    await cache_store.clear_prefix("plan:")
    await cache_store.delete("plans:all")
    await cache_store.delete("plans:public")
    await cache_store.load_all_plans()
    return {"status": "ok"}


@router.post("/refresh/system")
async def refresh_system_config(current_user: User = Depends(get_admin_user), session: AsyncSession = Depends(get_db_session)):
    await invalidate_system_config()
    result = await session.execute(text("SELECT key, value FROM system_config"))
    rows = result.fetchall()
    config_map = {r.key: r.value for r in rows}
    await cache_store.set("system:config", config_map)
    return {"status": "ok", "keys": len(config_map)}


@router.post("/refresh/llm")
async def refresh_llm_providers(current_user: User = Depends(get_admin_user), session: AsyncSession = Depends(get_db_session)):
    await invalidate_llm_providers()
    result = await session.execute(
        text("SELECT id, name, provider_type, config, is_active, is_default FROM llm_providers")
    )
    rows = result.fetchall()
    providers = []
    for r in rows:
        p = {"id": r.id, "name": r.name, "provider_type": r.provider_type,
             "config": r.config, "is_active": r.is_active, "is_default": r.is_default}
        providers.append(p)
    await cache_store.set("llm:providers", providers)
    return {"status": "ok", "providers": len(providers)}


@router.post("/refresh/languagetool")
async def refresh_lt_servers(current_user: User = Depends(get_admin_user), session: AsyncSession = Depends(get_db_session)):
    await invalidate_lt_servers()
    result = await session.execute(
        text("SELECT value FROM system_config WHERE key = 'grammar_checker_servers'")
    )
    row = result.fetchone()
    if row and row.value:
        import json
        servers = json.loads(row.value)
    else:
        servers = []
    await cache_store.set("languagetool:servers", servers)
    return {"status": "ok", "servers": len(servers)}
