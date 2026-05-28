import asyncio
import glob
import os

from asyncpg import create_pool


async def run_migrations(dsn: str, sql_dir: str = None):
    if sql_dir is None:
        sql_dir = os.path.join(os.path.dirname(__file__), "sql")

    pool = await create_pool(dsn, min_size=1, max_size=2)

    sql_files = sorted(glob.glob(os.path.join(sql_dir, "*.sql")))

    async with pool.acquire() as conn:
        for filepath in sql_files:
            filename = os.path.basename(filepath)
            print(f"Running migration: {filename}")
            with open(filepath) as f:
                sql = f.read()
            for statement in sql.split(";"):
                stmt = statement.strip()
                if stmt:
                    try:
                        await conn.execute(stmt)
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            print(f"  [skip] {filename}: {e}")
                        else:
                            print(f"  [error] {filename}: {e}")
                            raise
            print(f"  [done] {filename}")

    await pool.close()
    print("All migrations complete.")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from app.db.neon import _dsn

    asyncio.run(run_migrations(_dsn()))
