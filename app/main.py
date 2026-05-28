import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import add_exception_handlers
from app.api.v1 import health
from app.api.v1 import humanize, users, billing, plans, webhooks, public_plans, coupons, grammar
from app.api.v1.admin import dashboard, users as admin_users, billing as admin_billing, llm, plans as admin_plans, invites, system, pricing, cache as admin_cache

print("[STARTUP] Python:", sys.version, flush=True)
print("[STARTUP] APP_ENV:", settings.app_env, flush=True)
print("[STARTUP] All modules loaded", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Starting up...", flush=True)
    yield
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

print("[STARTUP] App ready to serve", flush=True)


@app.get("/", tags=["root"])
async def root():
    return {"app": "AiToHumanizer API", "version": "1.0.0"}
