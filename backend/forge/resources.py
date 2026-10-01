"""Durable external resource intents. External mutations never run under DB locks."""

import re
from datetime import timedelta
from uuid import UUID, uuid4

from forge.db import Database, many, one

KINDS = frozenset({"container", "volume", "network", "loop-scope"})
RETENTION = frozenset({"run", "preview", "app", "revision"})


class ResourceFenceError(RuntimeError):
    pass


class SettledDeleteFailure(RuntimeError):
    """Adapter proved the mutation ended without deleting the owned resource."""


class ResourceStore:
    def __init__(self, db: Database):
        self.db = db

    async def _lock_run(self, conn, run_id):
        identity = await one(conn, "SELECT app_id FROM runs WHERE id=%s", (run_id,))
        if identity is None:
            raise ResourceFenceError("resource run not found")
        app = await one(conn, "SELECT * FROM apps WHERE id=%s FOR UPDATE", (identity["app_id"],))
        run = await one(conn, "SELECT * FROM runs WHERE id=%s FOR UPDATE", (run_id,))
        now = (await one(conn, "SELECT clock_timestamp() AS now"))["now"]
        return app, run, now

    @staticmethod
    def _live(app, run, now, epoch):
        return (
            app["deleted_at"] is None
            and run["epoch"] == epoch
            and run["status"] == "running"
            and run["lease_until"] is not None
            and run["lease_until"] > now
            and run["deadline"] > now
        )

    @classmethod
    def _orphan(cls, app, run, now, row):
        retained = (
            app["deleted_at"] is None
            and row["adopted_revision"] is not None
            and row["retention"] in {"preview", "app", "revision"}
        )
        return not retained and not cls._live(app, run, now, row["epoch"])

    @staticmethod
    def _protected(app, row, now):
        return (
            row["adopted_revision"] is not None
            and row["retention"] in {"app", "revision"}
            and app["deleted_at"] is not None
            and app["deleted_at"] + timedelta(days=7) > now
        )

    async def reserve(self, run_id: UUID, epoch: int, *, slot: str, kind: str, retention="run"):
        if kind not in KINDS or retention not in RETENTION or not re.fullmatch(
            r"[a-z][a-z0-9-]{0,47}", slot
        ):
            raise ValueError("invalid resource intent")
        async with self.db.transaction() as conn:
            app, run, now = await self._lock_run(conn, run_id)
            if not self._live(app, run, now, epoch):
                raise ResourceFenceError("resource lease is not live")
            existing = await one(
                conn, "SELECT * FROM resources WHERE run_id=%s AND epoch=%s AND slot=%s",
                (run_id, epoch, slot),
            )
            if existing:
                if existing["kind"] != kind or existing["retention"] != retention:
                    raise ResourceFenceError("resource intent conflicts")
                return existing
            identity = uuid4()
            return await one(
                conn,
                "INSERT INTO resources(id,app_id,run_id,epoch,slot,kind,retention,external_name) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (identity, app["id"], run_id, epoch, slot, kind, retention,
                 f"forge-{kind}-{identity.hex}"),
            )

    async def _lock_resource(self, conn, identity):
        row = await one(conn, "SELECT run_id FROM resources WHERE id=%s", (identity,))
        if row is None:
            raise ResourceFenceError("resource intent not found")
        app, run, now = await self._lock_run(conn, row["run_id"])
        row = await one(conn, "SELECT * FROM resources WHERE id=%s FOR UPDATE", (identity,))
        return app, run, now, row

    async def begin_create(self, identity: UUID, epoch: int):
        async with self.db.transaction() as conn:
            app, run, now, row = await self._lock_resource(conn, identity)
            if (row["epoch"] != epoch or not self._live(app, run, now, epoch)
                    or row["cleanup_requested"] or row["state"] != "reserved"):
                raise ResourceFenceError("resource create is fenced")
            return await one(
                conn,
                "UPDATE resources SET state='creating',operation_id=%s,operation_action='create',"
                "updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                (uuid4(), identity),
            )

    async def complete_create(self, identity: UUID, operation: UUID):
        """Adapter acknowledges settled creation, even when cancellation requires later cleanup."""
        async with self.db.transaction() as conn:
            app, run, now, row = await self._lock_resource(conn, identity)
            if (row["operation_id"] != operation or row["operation_action"] != "create"
                    or row["state"] not in {"creating", "unknown"}):
                return False
            await conn.execute(
                "UPDATE resources SET state='ready',operation_id=NULL,operation_action=NULL,"
                "error_code=NULL,cleanup_requested=%s,updated_at=clock_timestamp() WHERE id=%s",
                (row["cleanup_requested"] or self._orphan(app, run, now, row), identity),
            )
            return True

    async def complete_create_absent(self, identity: UUID, operation: UUID):
        """Trusted adapter proved creation ended and left no resource, not just lookup absence."""
        async with self.db.transaction() as conn:
            _, _, _, row = await self._lock_resource(conn, identity)
            if (row["operation_id"] != operation or row["operation_action"] != "create"
                    or row["state"] not in {"creating", "unknown"}):
                return False
            await conn.execute(
                "UPDATE resources SET state='deleted',cleanup_requested=true,operation_id=NULL,"
                "operation_action=NULL,error_code=NULL,updated_at=clock_timestamp() WHERE id=%s",
                (identity,),
            )
            return True

    async def outcome_unknown(self, identity: UUID, operation: UUID):
        async with self.db.transaction() as conn:
            _, _, _, row = await self._lock_resource(conn, identity)
            if row["operation_id"] != operation or row["state"] not in {"creating", "deleting"}:
                return False
            await conn.execute(
                "UPDATE resources SET state='unknown',error_code='OUTCOME_UNKNOWN',"
                "updated_at=clock_timestamp() WHERE id=%s", (identity,),
            )
            return True

    async def request_cleanup(self, identity: UUID):
        async with self.db.transaction() as conn:
            await self._lock_resource(conn, identity)
            await conn.execute(
                "UPDATE resources SET cleanup_requested=true,updated_at=clock_timestamp() WHERE id=%s",
                (identity,),
            )

    async def claim_cleanup(self, *, limit=100):
        """No timer reissues uncertain external mutations. Returned intents have exclusive tokens."""
        if not 1 <= limit <= 100:
            raise ValueError("cleanup batch must be bounded")
        async with self.db.transaction() as conn:
            candidates = await many(
                conn,
                "SELECT x.id FROM resources x JOIN apps a ON a.id=x.app_id "
                "JOIN runs r ON r.id=x.run_id WHERE x.state NOT IN ('deleted','deleting') "
                "AND NOT (x.adopted_revision IS NOT NULL AND x.retention IN ('app','revision') "
                "AND a.deleted_at IS NOT NULL AND a.deleted_at+interval '7 days'>clock_timestamp()) "
                "AND (x.cleanup_requested OR NOT ("
                "(a.deleted_at IS NULL AND r.epoch=x.epoch AND r.status='running' "
                "AND r.lease_until>clock_timestamp() AND r.deadline>clock_timestamp()) OR "
                "(a.deleted_at IS NULL AND x.adopted_revision IS NOT NULL "
                "AND x.retention IN ('preview','app','revision')))) "
                "ORDER BY x.updated_at,x.id LIMIT %s", (limit,),
            )
        claimed = []
        for candidate in candidates:
            async with self.db.transaction() as conn:
                app, run, now, row = await self._lock_resource(conn, candidate["id"])
                if self._protected(app, row, now):
                    continue
                if not row["cleanup_requested"] and not self._orphan(app, run, now, row):
                    continue
                if row["state"] == "reserved":
                    await conn.execute(
                        "UPDATE resources SET state='deleted',cleanup_requested=true,"
                        "updated_at=clock_timestamp() WHERE id=%s", (row["id"],),
                    )
                elif row["state"] == "ready":
                    claimed.append(await one(
                        conn,
                        "UPDATE resources SET state='deleting',cleanup_requested=true,operation_id=%s,"
                        "operation_action='delete',updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                        (uuid4(), row["id"]),
                    ))
                elif row["state"] in {"creating", "unknown"}:
                    await conn.execute(
                        "UPDATE resources SET cleanup_requested=true,updated_at=clock_timestamp() "
                        "WHERE id=%s",
                        (row["id"],),
                    )
        return claimed

    async def complete_delete(self, identity: UUID, operation: UUID):
        """Only settled removal acknowledges deleted; an absent lookup alone is insufficient."""
        async with self.db.transaction() as conn:
            _, _, _, row = await self._lock_resource(conn, identity)
            if (row["operation_id"] != operation or row["operation_action"] != "delete"
                    or row["state"] not in {"deleting", "unknown"}):
                return False
            await conn.execute(
                "UPDATE resources SET state='deleted',operation_id=NULL,operation_action=NULL,"
                "error_code=NULL,updated_at=clock_timestamp() WHERE id=%s", (identity,),
            )
            return True

    async def delete_failed(self, identity: UUID, operation: UUID):
        """Settled failure permits a future retry; unknown failure must use outcome_unknown."""
        async with self.db.transaction() as conn:
            _, _, _, row = await self._lock_resource(conn, identity)
            if row["operation_id"] != operation or row["state"] != "deleting":
                return False
            await conn.execute(
                "UPDATE resources SET state='ready',operation_id=NULL,operation_action=NULL,"
                "error_code='DELETE_FAILED',updated_at=clock_timestamp() WHERE id=%s", (identity,),
            )
            return True

    async def unresolved(self, *, limit=100):
        """Operator diagnostics contain only owned identifiers, never adapter environment or logs."""
        if not 1 <= limit <= 100:
            raise ValueError("diagnostic batch must be bounded")
        async with self.db.transaction() as conn:
            return await many(
                conn,
                "SELECT id,app_id,run_id,epoch,kind,external_name,state,operation_id,operation_action,"
                "cleanup_requested,updated_at FROM resources "
                "WHERE state IN ('creating','deleting','unknown') "
                "ORDER BY updated_at,id LIMIT %s", (limit,),
            )

    async def reconcile(self, remove):
        """remove returns only after authoritative settled removal; all unclassified errors quarantine."""
        result = {"deleted": [], "retry": [], "unknown": []}
        for row in await self.claim_cleanup():
            identity, operation = row["id"], row["operation_id"]
            try:
                await remove(row)
            except SettledDeleteFailure:
                if await self.delete_failed(identity, operation):
                    result["retry"].append(identity)
            except Exception:
                if await self.outcome_unknown(identity, operation):
                    result["unknown"].append(identity)
            else:
                if await self.complete_delete(identity, operation):
                    result["deleted"].append(identity)
        return result
