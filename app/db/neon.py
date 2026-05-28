from asyncpg import create_pool, Pool
from app.core.config import settings


def _dsn() -> str:
    dsn = settings.database_url
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = "postgresql://" + dsn[len("postgresql+asyncpg://"):]
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(dsn)
    query = "&".join(
        p for p in parsed.query.split("&") if p and not p.startswith("sslmode=")
    )
    dsn = urlunparse(parsed._replace(query=query))
    return dsn


pool: Pool = None


async def init_db():
    global pool
    pool = await create_pool(
        _dsn(),
        min_size=2,
        max_size=10,
    )


async def close_db():
    global pool
    if pool:
        await pool.close()


async def get_db():
    global pool
    async with pool.acquire() as conn:
        yield conn
