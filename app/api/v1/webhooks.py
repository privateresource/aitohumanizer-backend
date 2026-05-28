import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.billing.webhook_handler import process_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/paddle")
async def paddle_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    raw_body = await request.body()
    result = await process_webhook(request, raw_body, session)
    logger.info("Webhook processed: %s", result)
    return {"status": "ok"}
