import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.exceptions import add_exception_handlers
from app.db.neon import init_db, close_db, _dsn
from app.db.base import Base
from app.api.deps import _clean_async_url
from app.api.v1 import humanize, users, billing, plans, health, webhooks, public_plans, coupons, grammar, moods
from app.api.v1.admin import dashboard, users as admin_users, billing as admin_billing, llm, plans as admin_plans, invites, system, pricing, cache as admin_cache


async def _ensure_sql_only_tables():
    import app.db.models
    engine = create_async_engine(_clean_async_url(settings.database_url))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    from asyncpg import create_pool
    pool = await create_pool(_dsn())
    async with pool.acquire() as conn:
        sql_dir = os.path.join(os.path.dirname(__file__), "db", "migrations", "sql")
        for fname in sorted(os.listdir(sql_dir)):
            if not fname.endswith(".sql"):
                continue
            if fname.startswith("0") and fname < "008":
                continue
            path = os.path.join(sql_dir, fname)
            with open(path) as f:
                content = f.read()
            for stmt in content.split(";"):
                s = stmt.strip()
                if s:
                    try:
                        await conn.execute(s)
                    except Exception as e:
                        msg = str(e).lower()
                        if "already exists" in msg or "does not exist" in msg:
                            continue
                        raise
    await pool.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _ensure_sql_only_tables()

    try:
        from app.cache import cache
        await cache.load_all_plans()
        print(f"[CACHE] Loaded {cache.stats()['total_keys']} keys from Neon")
    except Exception as e:
        import traceback
        print(f"[WARN] Cache init failed: {e}")
        traceback.print_exc()

    try:
        from app.api.deps import _get_session_factory
        from app.llm.init import init_providers
        factory = _get_session_factory()
        async with factory() as session:
            await init_providers(session)
    except Exception as e:
        import traceback
        print(f"[FATAL] init_providers failed: {e}")
        traceback.print_exc()

    yield
    await close_db()


app = FastAPI(
    title="AiToHumanizer API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.resolved_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

add_exception_handlers(app)

import os
uploads_dir = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

app.include_router(health.router, prefix="/api/v1")
app.include_router(plans.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(humanize.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(admin_users.router, prefix="/api/v1")
app.include_router(admin_billing.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(admin_plans.router, prefix="/api/v1")
app.include_router(invites.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api/v1")
app.include_router(pricing.router, prefix="/api/v1")
app.include_router(public_plans.router, prefix="/api/v1")
app.include_router(grammar.router, prefix="/api/v1")
app.include_router(coupons.router, prefix="/api/v1")
app.include_router(admin_cache.router, prefix="/api/v1")
app.include_router(moods.router, prefix="/api/v1")


@app.get("/", tags=["root"])
async def root():
    return {
        "app": "AiToHumanizer API",
        "version": "1.0.0",
        "docs": "/docs",
    }
