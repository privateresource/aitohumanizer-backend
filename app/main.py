import sys
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import add_exception_handlers
from app.api.v1 import health

# Track import errors
_import_errors: dict[str, str] = {}

def _safe_import(mod_name: str) -> object | None:
    try:
        return __import__(mod_name, fromlist=["router"])
    except Exception as e:
        _import_errors[mod_name] = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc()
        _import_errors[mod_name + "_traceback"] = tb
        print(f"[IMPORT ERROR] {mod_name}: {e}", flush=True)
        return None

humanize_mod = _safe_import("app.api.v1.humanize")
users_mod = _safe_import("app.api.v1.users")
billing_mod = _safe_import("app.api.v1.billing")
plans_mod = _safe_import("app.api.v1.plans")
webhooks_mod = _safe_import("app.api.v1.webhooks")
public_plans_mod = _safe_import("app.api.v1.public_plans")
coupons_mod = _safe_import("app.api.v1.coupons")
grammar_mod = _safe_import("app.api.v1.grammar")
admin_dashboard_mod = _safe_import("app.api.v1.admin.dashboard")
admin_users_mod = _safe_import("app.api.v1.admin.users")
admin_billing_mod = _safe_import("app.api.v1.admin.billing")
admin_llm_mod = _safe_import("app.api.v1.admin.llm")
admin_plans_mod = _safe_import("app.api.v1.admin.plans")
admin_invites_mod = _safe_import("app.api.v1.admin.invites")
admin_system_mod = _safe_import("app.api.v1.admin.system")
admin_pricing_mod = _safe_import("app.api.v1.admin.pricing")
admin_cache_mod = _safe_import("app.api.v1.admin.cache")

print(f"[STARTUP] Python: {sys.version}", flush=True)
print(f"[STARTUP] APP_ENV: {settings.app_env}", flush=True)
print(f"[STARTUP] Import errors: {len(_import_errors)}", flush=True)

from app.db.neon import init_db, close_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Starting up...", flush=True)
    try:
        await init_db()
        print("[INIT] DB pool created", flush=True)
    except Exception as e:
        print(f"[FATAL] init_db failed: {e}", flush=True)
        traceback.print_exc()
        print("[INIT] Continuing without DB", flush=True)

    import app.db.neon as neon_db
    if neon_db.pool:
        try:
            from app.db.base import Base
            from sqlalchemy.ext.asyncio import create_async_engine
            from app.api.deps import _clean_async_url
            from app.db.neon import _dsn
            import os, asyncpg

            engine = create_async_engine(_clean_async_url(settings.database_url))
            async with engine.begin() as conn:
                import app.db.models
                await conn.run_sync(Base.metadata.create_all)
            await engine.dispose()

            pool = await asyncpg.create_pool(_dsn())
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
            print("[INIT] Tables ensured", flush=True)
        except Exception as e:
            print(f"[FATAL] Table init failed: {e}", flush=True)
            traceback.print_exc()

        try:
            from app.cache import cache
            await cache.load_all_plans()
        except Exception as e:
            print(f"[WARN] Cache init failed: {e}", flush=True)

        try:
            from app.api.deps import _get_session_factory
            from app.llm.init import init_providers
            factory = _get_session_factory()
            async with factory() as session:
                await init_providers(session)
        except Exception as e:
            print(f"[FATAL] init_providers failed: {e}", flush=True)
            traceback.print_exc()

    yield
    await close_db()
    print("[LIFESPAN] Shutdown complete", flush=True)


app = FastAPI(title="AiToHumanizer API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.resolved_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
add_exception_handlers(app)

app.include_router(health.router, prefix="/api/v1")

def _add_router(mod, prefix: str):
    if mod and hasattr(mod, "router"):
        app.include_router(mod.router, prefix=prefix)

_add_router(plans_mod, "/api/v1")
_add_router(webhooks_mod, "/api/v1")
_add_router(humanize_mod, "/api/v1")
_add_router(users_mod, "/api/v1")
_add_router(billing_mod, "/api/v1")
_add_router(admin_dashboard_mod, "/api/v1")
_add_router(admin_users_mod, "/api/v1")
_add_router(admin_billing_mod, "/api/v1")
_add_router(admin_llm_mod, "/api/v1")
_add_router(admin_plans_mod, "/api/v1")
_add_router(admin_invites_mod, "/api/v1")
_add_router(admin_system_mod, "/api/v1")
_add_router(admin_pricing_mod, "/api/v1")
_add_router(public_plans_mod, "/api/v1")
_add_router(grammar_mod, "/api/v1")
_add_router(coupons_mod, "/api/v1")
_add_router(admin_cache_mod, "/api/v1")


@app.get("/api/v1/debug/imports")
async def debug_imports():
    return {
        "import_errors": {k: v for k, v in _import_errors.items() if not k.endswith("_traceback")},
        "python_version": sys.version,
        "app_env": settings.app_env,
    }


@app.get("/", tags=["root"])
async def root():
    return {"app": "AiToHumanizer API", "version": "1.0.0"}
