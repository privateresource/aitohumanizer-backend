import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_neon_auth_id(self, neon_auth_id: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.neon_auth_id == neon_auth_id)
        )
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update(self, user_id: uuid.UUID, data: dict) -> Optional[User]:
        data["updated_at"] = datetime.now(timezone.utc)
        stmt = update(User).where(User.id == user_id).values(**data).returning(User)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one_or_none()

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> tuple[list[User], int]:
        query = select(User)
        count_query = select(func.count(User.id))

        if role:
            query = query.where(User.role == role)
            count_query = count_query.where(User.role == role)
        if is_active is not None:
            query = query.where(User.is_active == is_active)
            count_query = count_query.where(User.is_active == is_active)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                (User.email.ilike(pattern)) | (User.full_name.ilike(pattern))
            )
            count_query = count_query.where(
                (User.email.ilike(pattern)) | (User.full_name.ilike(pattern))
            )

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        query = query.order_by(User.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        users = list(result.scalars().all())

        return users, total

    async def get_by_paddle_customer_id(self, customer_id: str) -> Optional[User]:
        from app.db.models.subscription import Subscription
        result = await self.session.execute(
            select(User).join(Subscription, User.id == Subscription.user_id).where(
                Subscription.paddle_customer_id == customer_id
            )
        )
        return result.scalar_one_or_none()

    async def soft_delete(self, user_id: uuid.UUID) -> Optional[User]:
        return await self.update(user_id, {"is_active": False})
