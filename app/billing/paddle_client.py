import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PADDLE_BASE = (
    "https://sandbox-api.paddle.com"
    if settings.paddle_environment == "sandbox"
    else "https://api.paddle.com"
)

_http_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=PADDLE_BASE,
            headers={
                "Authorization": f"Bearer {settings.paddle_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
    return _http_client


async def close_client():
    global _http_client
    if _http_client:
        await _http_client.aclose()
        _http_client = None


async def get_product_id_by_price(price_id: str) -> Optional[str]:
    client = _get_client()
    resp = await client.get(f"/prices/{price_id}")
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data.get("data", {}).get("product_id")


async def get_price(price_id: str) -> Optional[dict]:
    client = _get_client()
    resp = await client.get(f"/prices/{price_id}")
    if resp.status_code != 200:
        return None
    return resp.json().get("data")


async def create_transaction(
    price_id: str,
    customer_id: Optional[str] = None,
    items: Optional[list[dict]] = None,
) -> dict:
    client = _get_client()
    body: dict = {
        "items": items or [{"price_id": price_id, "quantity": 1}],
    }
    if customer_id:
        body["customer_id"] = customer_id

    resp = await client.post("/transactions", json=body)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return data


async def create_customer(email: str, name: Optional[str] = None) -> Optional[str]:
    client = _get_client()
    body: dict = {"email": email}
    if name:
        body["name"] = name
    resp = await client.post("/customers", json=body)
    if resp.status_code != 200 and resp.status_code != 201:
        return None
    return resp.json().get("data", {}).get("id")


async def search_customer(email: str) -> Optional[str]:
    client = _get_client()
    resp = await client.get("/customers", params={"search": email})
    if resp.status_code != 200:
        return None
    data = resp.json().get("data", [])
    if data:
        return data[0].get("id")
    return None


async def get_or_create_customer(email: str, name: Optional[str] = None) -> str:
    existing = await search_customer(email)
    if existing:
        return existing
    new_id = await create_customer(email, name)
    if new_id:
        return new_id
    raise RuntimeError("Failed to create Paddle customer")


async def create_customer_portal_session(customer_id: str) -> Optional[str]:
    client = _get_client()
    resp = await client.post(
        f"/customers/{customer_id}/portal-sessions",
        json={},
    )
    if resp.status_code != 200 and resp.status_code != 201:
        return None
    data = resp.json().get("data", {})
    return data.get("urls", {}).get("general", {}).get("overview")


async def get_subscription(subscription_id: str) -> Optional[dict]:
    client = _get_client()
    resp = await client.get(f"/subscriptions/{subscription_id}")
    if resp.status_code != 200:
        return None
    return resp.json().get("data")


async def preview_update_subscription(
    subscription_id: str,
    price_id: str,
    billing_cycle: Optional[str] = None,
    proration_billing_mode: str = "prorated_immediately",
) -> Optional[dict]:
    client = _get_client()
    body = {
        "items": [{"price_id": price_id, "quantity": 1}],
        "proration_billing_mode": proration_billing_mode,
    }
    resp = await client.patch(
        f"/subscriptions/{subscription_id}/preview",
        json=body,
    )
    if resp.status_code != 200:
        return None
    return resp.json().get("data")


async def cancel_subscription(subscription_id: str) -> bool:
    client = _get_client()
    resp = await client.post(
        f"/subscriptions/{subscription_id}/cancel",
        json={"effective_from": "next_billing_period"},
    )
    return resp.status_code == 200


async def list_prices(product_ids: Optional[list[str]] = None) -> list[dict]:
    client = _get_client()
    params: dict = {"status": "active"}
    resp = await client.get("/prices", params=params)
    if resp.status_code != 200:
        return []
    data = resp.json().get("data", [])
    if product_ids:
        data = [p for p in data if p.get("product_id") in product_ids]
    return data


async def create_price(
    product_id: str,
    name: str,
    amount: str,
    interval: str,
    description: str = "",
    currency: str = "USD",
    tax_mode: str = "external",
) -> Optional[str]:
    client = _get_client()
    body = {
        "name": name,
        "description": description or name,
        "product_id": product_id,
        "unit_price": {"amount": amount, "currency_code": currency},
        "billing_cycle": {"interval": interval, "frequency": 1},
        "tax_mode": tax_mode,
    }
    resp = await client.post("/prices", json=body)
    if resp.status_code != 201 and resp.status_code != 200:
        try:
            err = resp.json()
            logger.error("Paddle create_price failed: %s - %s", resp.status_code, err)
        except Exception:
            logger.error("Paddle create_price failed: %s %s", resp.status_code, resp.text[:500])
        return None
    return resp.json().get("data", {}).get("id")


async def list_customer_transactions(
    customer_id: str,
    status: str = "completed",
    per_page: int = 50,
) -> list[dict]:
    client = _get_client()
    all_txns = []
    after = None
    while True:
        params: dict = {
            "customer_id": customer_id,
            "status": status,
            "per_page": min(per_page, 50),
        }
        if after:
            params["after"] = after
        resp = await client.get("/transactions", params=params)
        if resp.status_code != 200:
            break
        data = resp.json()
        items = data.get("data", [])
        all_txns.extend(items)
        meta = data.get("meta", {})
        pagination = meta.get("pagination", {})
        if not pagination.get("has_more"):
            break
        after = pagination.get("next_cursor")
    return all_txns


async def list_all_transactions(
    status: str = "completed",
    per_page: int = 50,
) -> list[dict]:
    client = _get_client()
    all_txns = []
    after = None
    while True:
        params: dict = {
            "status": status,
            "per_page": min(per_page, 50),
        }
        if after:
            params["after"] = after
        resp = await client.get("/transactions", params=params)
        if resp.status_code != 200:
            break
        data = resp.json()
        items = data.get("data", [])
        all_txns.extend(items)
        meta = data.get("meta", {})
        pagination = meta.get("pagination", {})
        if not pagination.get("has_more"):
            break
        after = pagination.get("next_cursor")
    return all_txns


async def create_product(name: str, description: str = "") -> Optional[str]:
    client = _get_client()
    body = {
        "name": name,
        "description": description,
        "tax_category": "standard",
    }
    resp = await client.post("/products", json=body)
    if resp.status_code != 201 and resp.status_code != 200:
        return None
    return resp.json().get("data", {}).get("id")
