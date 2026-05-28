import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Depends as FastAPIDepends
from app.api.deps import get_db_session, get_admin_user, get_current_user
from app.core.exceptions import BadRequestException, NotFoundException, ForbiddenException
from app.core.config import settings
from app.db.models.user import User
from app.db.models.admin_invite import AdminInvite
from app.db.repositories.admin_repo import AdminRepository
from app.db.repositories.user_repo import UserRepository

router = APIRouter(prefix="/admin/invites", tags=["admin"])


class InviteResponse(BaseModel):
    id: str
    email: str
    role: str
    token: str
    invited_by: Optional[str] = None
    is_used: bool
    expires_at: str
    used_at: Optional[str] = None
    used_by_user_id: Optional[str] = None
    created_at: str


class InviteCreateRequest(BaseModel):
    email: str
    role: str = "admin"


class InviteCreateResponse(BaseModel):
    id: str
    email: str
    role: str
    token: str
    expires_at: str
    message: str


class InviteAcceptRequest(BaseModel):
    token: str


class InviteAcceptResponse(BaseModel):
    id: str
    email: str
    role: str
    message: str


class DeleteResponse(BaseModel):
    status: str
    message: str
    id: str


@router.get("", response_model=list[InviteResponse])
async def list_invites(
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    from sqlalchemy import select, func
    from app.db.models.admin_invite import AdminInvite

    result = await session.execute(
        select(AdminInvite).order_by(AdminInvite.created_at.desc())
    )
    invites = list(result.scalars().all())

    return [
        InviteResponse(
            id=str(inv.id),
            email=inv.email,
            role=inv.role,
            token=inv.token,
            invited_by=str(inv.invited_by) if inv.invited_by else None,
            is_used=inv.is_used,
            expires_at=inv.expires_at.isoformat(),
            used_at=inv.used_at.isoformat() if inv.used_at else None,
            used_by_user_id=str(inv.used_by_user_id) if inv.used_by_user_id else None,
            created_at=inv.created_at.isoformat(),
        )
        for inv in invites
    ]


@router.post("", response_model=InviteCreateResponse, status_code=201)
async def create_invite(
    req: InviteCreateRequest,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    from app.core.constants import ROLE_HIERARCHY

    if req.role not in ROLE_HIERARCHY:
        raise BadRequestException(
            message=f"Invalid role. Must be one of: {', '.join(ROLE_HIERARCHY.keys())}"
        )

    current_level = ROLE_HIERARCHY.get(current_user.role, 0)
    target_level = ROLE_HIERARCHY.get(req.role, 0)
    if target_level >= current_level and current_user.role != "superadmin":
        raise ForbiddenException(
            message="You cannot invite users with a role equal to or higher than yours"
        )

    user_repo = UserRepository(session)
    existing_user = await user_repo.get_by_email(req.email)
    if existing_user:
        if existing_user.role in ("admin", "manager", "superadmin"):
            raise BadRequestException(
                message=f"User {req.email} already has admin role ({existing_user.role})"
            )

    from sqlalchemy import select
    existing_invite = await session.execute(
        select(AdminInvite).where(
            AdminInvite.email == req.email,
            AdminInvite.is_used == False,
            AdminInvite.expires_at > datetime.now(timezone.utc),
        )
    )
    if existing_invite.scalar_one_or_none():
        raise BadRequestException(
            message=f"An active invite already exists for {req.email}"
        )

    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    admin_repo = AdminRepository(session)
    invite = AdminInvite(
        email=req.email,
        token=token,
        role=req.role,
        invited_by=current_user.id,
        is_used=False,
        expires_at=expires_at,
    )
    created = await admin_repo.create_invite(invite)

    try:
        await _send_invite_email(req.email, token, req.role, current_user.full_name)
    except Exception:
        pass

    return InviteCreateResponse(
        id=str(created.id),
        email=created.email,
        role=created.role,
        token=token,
        expires_at=expires_at.isoformat(),
        message=f"Invite sent to {req.email}",
    )


async def _send_invite_email(email: str, token: str, role: str, inviter_name: Optional[str]):
    from app.core.config import settings

    invite_url = f"{settings.frontend_url}/admin/accept-invite?token={token}"

    try:
        import resend
        resend.api_key = settings.resend_api_key

        params = {
            "from": f"{settings.email_from_name} <{settings.email_from}>",
            "to": [email],
            "subject": f"You've been invited to be an {role} on AiToHumanizer",
            "html": f"""
            <h2>Admin Invitation</h2>
            <p>{inviter_name or 'An admin'} has invited you to join AiToHumanizer as an <strong>{role}</strong>.</p>
            <p>Click the link below to accept the invitation:</p>
            <p><a href="{invite_url}" style="display:inline-block;padding:12px 24px;background:#4F46E5;color:white;text-decoration:none;border-radius:6px;">Accept Invitation</a></p>
            <p>This invite expires in 7 days.</p>
            """,
        }
        await resend.Emails.send_async(params)
    except ImportError:
        pass
    except Exception:
        pass


@router.delete("/{invite_id}", response_model=DeleteResponse)
async def revoke_invite(
    invite_id: uuid.UUID,
    current_user: User = Depends(get_admin_user),
    session: AsyncSession = Depends(get_db_session),
):
    from sqlalchemy import select
    from app.db.models.admin_invite import AdminInvite

    result = await session.execute(
        select(AdminInvite).where(AdminInvite.id == invite_id)
    )
    invite = result.scalar_one_or_none()
    if not invite:
        raise NotFoundException(message="Invite not found")

    if invite.is_used:
        raise BadRequestException(message="Cannot revoke an already used invite")

    await session.delete(invite)
    await session.commit()

    return DeleteResponse(
        status="revoked",
        message=f"Invite for {invite.email} has been revoked",
        id=str(invite_id),
    )


@router.post("/accept", response_model=InviteAcceptResponse)
async def accept_invite(
    req: InviteAcceptRequest,
    current_user: User = FastAPIDepends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    admin_repo = AdminRepository(session)
    user_repo = UserRepository(session)

    invite = await admin_repo.get_invite_by_token(req.token)
    if not invite:
        raise NotFoundException(message="Invalid or expired invite token")

    if invite.is_used:
        raise BadRequestException(message="This invite has already been used")

    if invite.expires_at < datetime.now(timezone.utc):
        raise BadRequestException(message="This invite has expired")

    if invite.email != current_user.email:
        raise BadRequestException(
            message=f"This invite was sent to {invite.email}, but you are logged in as {current_user.email}"
        )

    await admin_repo.mark_invite_used(invite.id, current_user.id)
    await user_repo.update(current_user.id, {"role": invite.role})

    return InviteAcceptResponse(
        id=str(invite.id),
        email=invite.email,
        role=invite.role,
        message=f"You are now an {invite.role} on AiToHumanizer",
    )

