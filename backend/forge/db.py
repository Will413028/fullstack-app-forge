from contextlib import asynccontextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from forge.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.pool = AsyncConnectionPool(
            settings.database_url,
            open=False,
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row},
        )

    async def open(self):
        try:
            await self.pool.open(wait=True)
            await self.migrate()
        except BaseException:
            await self.pool.close()
            raise

    async def migrate(self):
        async with self.transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(7319401)")
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_versions (version integer PRIMARY KEY,"
                "applied_at timestamptz NOT NULL DEFAULT clock_timestamp())"
            )
            migrations = sorted(Path(__file__).with_name("migrations").glob("[0-9][0-9][0-9]_*.sql"))
            versions = [int(path.name[:3]) for path in migrations]
            if versions != list(range(1, len(versions) + 1)):
                raise RuntimeError("platform migration sequence invalid")
            applied = [
                row["version"]
                for row in await many(conn, "SELECT version FROM schema_versions ORDER BY version")
            ]
            if applied != list(range(1, len(applied) + 1)) or len(applied) > len(versions):
                raise RuntimeError("platform database version incompatible with runtime")
            for version, path in zip(versions, migrations, strict=True):
                if version > len(applied):
                    await conn.execute(path.read_text())
                    await conn.execute("INSERT INTO schema_versions(version) VALUES(%s)", (version,))

    async def close(self):
        await self.pool.close()

    @asynccontextmanager
    async def transaction(self):
        async with self.pool.connection() as conn, conn.transaction():
            yield conn


async def one(conn, query, params=()):
    cursor = await conn.execute(query, params)
    return await cursor.fetchone()


async def many(conn, query, params=()):
    cursor = await conn.execute(query, params)
    return await cursor.fetchall()
