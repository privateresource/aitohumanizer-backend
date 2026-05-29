import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_current_user
from app.core.exceptions import BadRequestException, NotFoundException
from app.db.models.user import User

router = APIRouter(prefix="/moods", tags=["moods"])

BUILT_IN_MOODS: dict[str, str] = {
    "neutral": "No specific tone adjustment.",
    "confident": "Direct, assertive, no hedging.",
    "casual": "Relaxed, conversational, like texting a friend.",
    "formal": "Polished, structured, professional distance.",
    "storytelling": "Narrative flow, engaging, scene-setting.",
    "persuasive": "Compelling, rhetorical, conviction-driven.",
}


class MoodItem(BaseModel):
    id: str
    name: str
    prompt: str
    is_built_in: bool = False
    created_at: str = ""
    updated_at: str = ""


class CreateMoodRequest(BaseModel):
    name: str
    prompt: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        if len(v) > 100:
            raise ValueError("Name must be 100 characters or fewer")
        return v

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Prompt cannot be empty")
        if len(v) > 200:
            raise ValueError("Prompt must be 200 characters or fewer")
        return v


class UpdateMoodRequest(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Name cannot be empty")
            if len(v) > 100:
                raise ValueError("Name must be 100 characters or fewer")
        return v

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Prompt cannot be empty")
            if len(v) > 200:
                raise ValueError("Prompt must be 200 characters or fewer")
        return v


@router.get("/built-in", response_model=list[MoodItem])
async def list_built_in_moods():
    return [
        MoodItem(id=k, name=k.capitalize(), prompt=v, is_built_in=True)
        for k, v in BUILT_IN_MOODS.items()
    ]


@router.get("", response_model=list[MoodItem])
async def list_user_moods(
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    query = "SELECT * FROM user_moods WHERE user_id = :uid"
    params: dict = {"uid": current_user.id}

    if search:
        query += " AND (name ILIKE :search OR prompt ILIKE :search)"
        params["search"] = f"%{search}%"

    query += " ORDER BY created_at DESC"
    result = await session.execute(text(query), params)
    rows = result.fetchall()

    return [
        MoodItem(
            id=str(r.id),
            name=r.name,
            prompt=r.prompt,
            created_at=r.created_at.isoformat(),
            updated_at=r.updated_at.isoformat(),
        )
        for r in rows
    ]


@router.post("", response_model=MoodItem, status_code=201)
async def create_mood(
    req: CreateMoodRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    from app.pricing.usage import get_user_plan_features

    features = await get_user_plan_features(session, current_user.id)
    max_moods = int(features.get("max_custom_moods", 0))

    if max_moods <= 0:
        raise BadRequestException(
            message="Your plan does not support custom moods. Upgrade to create moods."
        )

    count = await session.execute(
        text("SELECT COUNT(*) FROM user_moods WHERE user_id = :uid"),
        {"uid": current_user.id},
    )
    if count.scalar() >= max_moods:
        raise BadRequestException(
            message=f"You have reached your plan limit of {max_moods} custom moods. Upgrade to create more."
        )

    mood_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await session.execute(
        text("""
            INSERT INTO user_moods (id, user_id, name, prompt, created_at, updated_at)
            VALUES (:id, :uid, :name, :prompt, :now, :now)
        """),
        {
            "id": mood_id,
            "uid": current_user.id,
            "name": req.name,
            "prompt": req.prompt,
            "now": now,
        },
    )
    await session.commit()

    return MoodItem(
        id=str(mood_id),
        name=req.name,
        prompt=req.prompt,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )


@router.put("/{mood_id}", response_model=MoodItem)
async def update_mood(
    mood_id: str,
    req: UpdateMoodRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    row = await session.execute(
        text("SELECT * FROM user_moods WHERE id = :id AND user_id = :uid"),
        {"id": mood_id, "uid": current_user.id},
    )
    existing = row.fetchone()
    if not existing:
        raise NotFoundException(message="Mood not found")

    updates = []
    params = {"id": mood_id, "now": datetime.now(timezone.utc)}

    if req.name is not None:
        updates.append("name = :name")
        params["name"] = req.name
    if req.prompt is not None:
        updates.append("prompt = :prompt")
        params["prompt"] = req.prompt

    if not updates:
        raise BadRequestException(message="No fields to update")

    updates.append("updated_at = :now")
    await session.execute(
        text(f"UPDATE user_moods SET {', '.join(updates)} WHERE id = :id"),
        params,
    )
    await session.commit()

    return MoodItem(
        id=str(existing.id),
        name=req.name or existing.name,
        prompt=req.prompt or existing.prompt,
        created_at=existing.created_at.isoformat(),
        updated_at=params["now"].isoformat(),
    )


@router.delete("/{mood_id}")
async def delete_mood(
    mood_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        text("DELETE FROM user_moods WHERE id = :id AND user_id = :uid RETURNING id"),
        {"id": mood_id, "uid": current_user.id},
    )
    if not result.fetchone():
        raise NotFoundException(message="Mood not found")
    await session.commit()
    return {"status": "deleted"}
