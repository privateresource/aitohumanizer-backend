import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_admin_user
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.user import User
from app.llm.keys.key_manager import encrypt_key, decrypt_key, mask_key

router = APIRouter(prefix="/admin/llm", tags=["admin"])

PROVIDERS_TABLE = "llm_providers"
KEYS_TABLE = "llm_provider_keys"
FALLBACK_TABLE = "llm_fallback_config"


class ProviderResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    config: dict
    is_active: bool
    is_default: bool
    created_at: str
    updated_at: str


class ProviderCreateRequest(BaseModel):
    name: str
    provider_type: str
    base_url: str = ""
    default_model: str = ""
    api_key: str = ""
    max_tokens: int = 4096
    max_input_chars: int = 12000


class ProviderUpdateRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    api_key: Optional[str] = None
    max_tokens: Optional[int] = None
    max_input_chars: Optional[int] = None
    is_active: Optional[bool] = None


class KeyResponse(BaseModel):
    id: str
    provider_id: str
    label: str
    masked_key: str
    is_active: bool
    is_parked: bool
    created_at: str


class KeyCreateRequest(BaseModel):
    label: str
    api_key: str



async def _reload_providers(session: AsyncSession):
    from app.llm.init import init_providers
    await init_providers(session)


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    result = await session.execute(
        text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :name)"),
        {"name": table_name},
    )
    return result.scalar_one()


async def _ensure_providers_table(session: AsyncSession):
    if not await _table_exists(session, PROVIDERS_TABLE):
        await session.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {PROVIDERS_TABLE} (
                id UUID PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                provider_type VARCHAR(100) NOT NULL,
                config JSONB DEFAULT '{{}}',
                is_active BOOLEAN DEFAULT TRUE,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()
    else:
        try:
            await session.execute(text(f"""
                ALTER TABLE {PROVIDERS_TABLE} ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE
            """))
            await session.commit()
        except Exception:
            await session.rollback()


async def _ensure_keys_table(session: AsyncSession):
    if not await _table_exists(session, KEYS_TABLE):
        await session.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {KEYS_TABLE} (
                id UUID PRIMARY KEY,
                provider_id UUID NOT NULL REFERENCES {PROVIDERS_TABLE}(id) ON DELETE CASCADE,
                label VARCHAR(255) NOT NULL,
                encrypted_key TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                is_parked BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()



@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    result = await session.execute(
        text(f"SELECT * FROM {PROVIDERS_TABLE} ORDER BY created_at DESC")
    )
    rows = result.fetchall()
    return [
        ProviderResponse(
            id=str(r.id),
            name=r.name,
            provider_type=r.provider_type,
            config=r.config or {},
            is_active=r.is_active,
            is_default=getattr(r, "is_default", False),
            created_at=r.created_at.isoformat(),
            updated_at=r.updated_at.isoformat(),
        )
        for r in rows
    ]


@router.post("/providers", response_model=ProviderResponse, status_code=201)
async def create_provider(
    req: ProviderCreateRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    if req.provider_type not in ("openai_compatible", "anthropic"):
        raise BadRequestException(
            message=f"Unsupported provider type: {req.provider_type}",
            detail={"supported": ["openai_compatible", "anthropic"]},
        )

    await _ensure_providers_table(session)
    provider_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    config = {
        "base_url": req.base_url,
        "default_model": req.default_model,
        "max_tokens": req.max_tokens,
        "max_input_chars": req.max_input_chars,
    }

    await session.execute(
        text(f"""
            INSERT INTO {PROVIDERS_TABLE} (id, name, provider_type, config, is_active, created_at, updated_at)
            VALUES (:id, :name, :type, :config, TRUE, :now, :now)
        """),
        {
            "id": provider_id,
            "name": req.name,
            "type": req.provider_type,
            "config": json.dumps(config),
            "now": now,
        },
    )
    await session.commit()

    if req.api_key:
        key_id = str(uuid.uuid4())
        encrypted = encrypt_key(req.api_key)
        await _ensure_keys_table(session)
        await session.execute(
            text(f"""
                INSERT INTO {KEYS_TABLE} (id, provider_id, label, encrypted_key, is_active, is_parked, created_at, updated_at)
                VALUES (:id, :pid, :label, :ekey, TRUE, FALSE, :now, :now)
            """),
            {"id": key_id, "pid": provider_id, "label": f"{req.name} default", "ekey": encrypted, "now": now},
        )
        await session.commit()

    await _reload_providers(session)

    is_default = False
    if req.api_key:
        existing = await session.execute(
            text(f"SELECT COUNT(*) FROM {PROVIDERS_TABLE}")
        )
        count = existing.scalar_one()
        if count == 1:
            is_default = True
            await session.execute(
                text(f"UPDATE {PROVIDERS_TABLE} SET is_default = TRUE WHERE id = :id"),
                {"id": provider_id},
            )
            await session.commit()

    return ProviderResponse(
        id=provider_id,
        name=req.name,
        provider_type=req.provider_type,
        config=config,
        is_active=True,
        is_default=is_default,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )


@router.get("/providers/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    result = await session.execute(
        text(f"SELECT * FROM {PROVIDERS_TABLE} WHERE id = :id"),
        {"id": provider_id},
    )
    row = result.fetchone()
    if not row:
        raise NotFoundException(message="Provider not found")

    return ProviderResponse(
        id=str(row.id),
        name=row.name,
        provider_type=row.provider_type,
        config=row.config or {},
        is_active=row.is_active,
        is_default=getattr(row, "is_default", False),
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


@router.patch("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str, req: ProviderUpdateRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    updates = []
    params = {"id": provider_id}

    if req.name is not None:
        updates.append("name = :name")
        params["name"] = req.name
    if req.is_active is not None:
        updates.append("is_active = :active")
        params["active"] = req.is_active

    config_updates = {}
    if req.base_url is not None:
        config_updates["base_url"] = req.base_url
    if req.default_model is not None:
        config_updates["default_model"] = req.default_model
    if req.max_tokens is not None:
        config_updates["max_tokens"] = req.max_tokens
    if req.max_input_chars is not None:
        config_updates["max_input_chars"] = req.max_input_chars

    if config_updates:
        import json
        existing = await session.execute(
            text(f"SELECT config FROM {PROVIDERS_TABLE} WHERE id = :id"),
            {"id": provider_id},
        )
        row_existing = existing.fetchone()
        current_config = dict(row_existing.config) if row_existing and row_existing.config else {}
        current_config.update(config_updates)
        updates.append("config = :config")
        params["config"] = json.dumps(current_config)

    if req.api_key is not None:
        await _ensure_keys_table(session)
        encrypted = encrypt_key(req.api_key)
        now = datetime.now(timezone.utc)
        key_id = str(uuid.uuid4())
        existing_key = await session.execute(
            text(f"SELECT id FROM {KEYS_TABLE} WHERE provider_id = :pid LIMIT 1"),
            {"pid": provider_id},
        )
        key_row = existing_key.fetchone()
        if key_row:
            await session.execute(
                text(f"UPDATE {KEYS_TABLE} SET encrypted_key = :ekey, updated_at = :now WHERE id = :kid"),
                {"ekey": encrypted, "now": now, "kid": key_row.id},
            )
        else:
            await session.execute(
                text(f"INSERT INTO {KEYS_TABLE} (id, provider_id, label, encrypted_key, is_active, is_parked, created_at, updated_at) VALUES (:id, :pid, :label, :ekey, TRUE, FALSE, :now, :now)"),
                {"id": key_id, "pid": provider_id, "label": f"{req.name or provider_id} key", "ekey": encrypted, "now": now},
            )

    if not updates and req.api_key is None:
        raise BadRequestException(message="No fields to update")

    updates.append("updated_at = :now")
    params["now"] = datetime.now(timezone.utc)
    await session.execute(
        text(f"UPDATE {PROVIDERS_TABLE} SET {', '.join(updates)} WHERE id = :id"),
        params,
    )
    await session.commit()
    await _reload_providers(session)
    return await get_provider(provider_id, current_user, session)


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    await session.execute(
        text(f"DELETE FROM {PROVIDERS_TABLE} WHERE id = :id"),
        {"id": provider_id},
    )
    await session.commit()
    await _reload_providers(session)
    return {"status": "deleted", "id": provider_id}


@router.post("/providers/{provider_id}/activate", response_model=ProviderResponse)
async def activate_provider(
    provider_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    await session.execute(
        text(f"UPDATE {PROVIDERS_TABLE} SET is_active = TRUE, updated_at = :now WHERE id = :id"),
        {"id": provider_id, "now": datetime.now(timezone.utc)},
    )
    await session.commit()
    await _reload_providers(session)
    return await get_provider(provider_id, current_user, session)


@router.post("/providers/{provider_id}/deactivate", response_model=ProviderResponse)
async def deactivate_provider(
    provider_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    await session.execute(
        text(f"UPDATE {PROVIDERS_TABLE} SET is_active = FALSE, updated_at = :now WHERE id = :id"),
        {"id": provider_id, "now": datetime.now(timezone.utc)},
    )
    await session.commit()
    await _reload_providers(session)
    return await get_provider(provider_id, current_user, session)


@router.post("/providers/{provider_id}/set-default", response_model=ProviderResponse)
async def set_default_provider(
    provider_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    now = datetime.now(timezone.utc)

    await session.execute(
        text(f"UPDATE {PROVIDERS_TABLE} SET is_default = FALSE, updated_at = :now WHERE is_default = TRUE"),
        {"now": now},
    )
    await session.execute(
        text(f"UPDATE {PROVIDERS_TABLE} SET is_default = TRUE, updated_at = :now WHERE id = :id"),
        {"id": provider_id, "now": now},
    )
    await session.commit()
    await _reload_providers(session)
    return await get_provider(provider_id, current_user, session)


@router.get("/default", response_model=Optional[ProviderResponse])
async def get_default_provider(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    result = await session.execute(
        text(f"SELECT * FROM {PROVIDERS_TABLE} WHERE is_default = TRUE LIMIT 1")
    )
    row = result.fetchone()
    if not row:
        return None
    return ProviderResponse(
        id=str(row.id),
        name=row.name,
        provider_type=row.provider_type,
        config=row.config or {},
        is_active=row.is_active,
        is_default=True,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


class TestResult(BaseModel):
    success: bool
    provider_id: str
    message: str
    latency_ms: int


@router.post("/providers/{provider_id}/test", response_model=TestResult)
async def test_provider(
    provider_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    await _ensure_keys_table(session)
    result = await session.execute(
        text(f"SELECT * FROM {PROVIDERS_TABLE} WHERE id = :id"),
        {"id": provider_id},
    )
    row = result.fetchone()
    if not row:
        raise NotFoundException(message="Provider not found")

    key_result = await session.execute(
        text(f"SELECT * FROM {KEYS_TABLE} WHERE provider_id = :pid AND is_active = TRUE AND is_parked = FALSE LIMIT 1"),
        {"pid": provider_id},
    )
    key_row = key_result.fetchone()
    if not key_row:
        raise BadRequestException(message="No active key found for this provider")

    api_key = decrypt_key(key_row.encrypted_key)
    config = row.config or {}
    provider_type = row.provider_type
    base_url = config.get("base_url", "")
    default_model = config.get("default_model", "")

    import httpx, time
    start = time.monotonic()
    success = False
    try:
        if provider_type == "anthropic":
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=api_key, max_retries=0, timeout=httpx.Timeout(10))
            await client.models.list()
            success = True
        else:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            url = f"{base_url.rstrip('/')}/models"
            async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
                response = await client.get(url, headers=headers)
                success = response.status_code == 200
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return TestResult(success=False, provider_id=provider_id, message=str(e), latency_ms=elapsed)

    elapsed = int((time.monotonic() - start) * 1000)
    return TestResult(
        success=success, provider_id=provider_id,
        message="Connection successful" if success else "Connection failed",
        latency_ms=elapsed,
    )


@router.get("/providers/{provider_id}/keys", response_model=list[KeyResponse])
async def list_keys(
    provider_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_keys_table(session)
    result = await session.execute(
        text(f"SELECT * FROM {KEYS_TABLE} WHERE provider_id = :pid ORDER BY created_at DESC"),
        {"pid": provider_id},
    )
    rows = result.fetchall()
    return [
        KeyResponse(
            id=str(r.id),
            provider_id=str(r.provider_id),
            label=r.label,
            masked_key=mask_key(r.encrypted_key),
            is_active=r.is_active,
            is_parked=r.is_parked,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.post("/providers/{provider_id}/keys", response_model=KeyResponse, status_code=201)
async def create_key(
    provider_id: str,
    req: KeyCreateRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_providers_table(session)
    await _ensure_keys_table(session)

    key_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    encrypted = encrypt_key(req.api_key)

    await session.execute(
        text(f"""
            INSERT INTO {KEYS_TABLE} (id, provider_id, label, encrypted_key, is_active, is_parked, created_at, updated_at)
            VALUES (:id, :pid, :label, :ekey, TRUE, FALSE, :now, :now)
        """),
        {"id": key_id, "pid": provider_id, "label": req.label, "ekey": encrypted, "now": now},
    )
    await session.commit()
    await _reload_providers(session)

    return KeyResponse(
        id=key_id,
        provider_id=provider_id,
        label=req.label,
        masked_key=mask_key(encrypted),
        is_active=True,
        is_parked=False,
        created_at=now.isoformat(),
    )


@router.delete("/providers/{provider_id}/keys/{key_id}")
async def delete_key(
    provider_id: str,
    key_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_keys_table(session)
    await session.execute(
        text(f"DELETE FROM {KEYS_TABLE} WHERE id = :kid AND provider_id = :pid"),
        {"kid": key_id, "pid": provider_id},
    )
    await session.commit()
    await _reload_providers(session)
    return {"status": "deleted", "key_id": key_id}


@router.post("/providers/{provider_id}/keys/{key_id}/park", response_model=KeyResponse)
async def park_key(
    provider_id: str,
    key_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_keys_table(session)
    now = datetime.now(timezone.utc)
    await session.execute(
        text(f"UPDATE {KEYS_TABLE} SET is_parked = TRUE, updated_at = :now WHERE id = :kid AND provider_id = :pid"),
        {"kid": key_id, "pid": provider_id, "now": now},
    )
    await session.commit()
    await _reload_providers(session)

    result = await session.execute(
        text(f"SELECT * FROM {KEYS_TABLE} WHERE id = :kid"),
        {"kid": key_id},
    )
    row = result.fetchone()
    return KeyResponse(
        id=str(row.id),
        provider_id=str(row.provider_id),
        label=row.label,
        masked_key=mask_key(row.encrypted_key),
        is_active=row.is_active,
        is_parked=row.is_parked,
        created_at=row.created_at.isoformat(),
    )


@router.post("/providers/{provider_id}/keys/{key_id}/unpark", response_model=KeyResponse)
async def unpark_key(
    provider_id: str,
    key_id: str,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    await _ensure_keys_table(session)
    now = datetime.now(timezone.utc)
    await session.execute(
        text(f"UPDATE {KEYS_TABLE} SET is_parked = FALSE, updated_at = :now WHERE id = :kid AND provider_id = :pid"),
        {"kid": key_id, "pid": provider_id, "now": now},
    )
    await session.commit()
    await _reload_providers(session)

    result = await session.execute(
        text(f"SELECT * FROM {KEYS_TABLE} WHERE id = :kid"),
        {"kid": key_id},
    )
    row = result.fetchone()
    return KeyResponse(
        id=str(row.id),
        provider_id=str(row.provider_id),
        label=row.label,
        masked_key=mask_key(row.encrypted_key),
        is_active=row.is_active,
        is_parked=row.is_parked,
        created_at=row.created_at.isoformat(),
    )



