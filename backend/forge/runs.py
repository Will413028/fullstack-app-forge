import hashlib
import json
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from forge.config import Settings
from forge.db import Database, many, one
from forge.models import RunInput
from forge.security import forbidden

TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


def request_hash(body: RunInput) -> str:
    canonical = {"request": body.model_dump(mode="json"), "template_version": "1"}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def owned_app(conn, owner_id: UUID, app_id: UUID, *, lock=False):
    row = await one(
        conn,
        "SELECT * FROM apps WHERE id=%s AND owner_id=%s AND deleted_at IS NULL"
        + (" FOR UPDATE" if lock else ""),
        (app_id, owner_id),
    )
    if row is None:
        forbidden("NOT_FOUND", 404)
    return row


async def append_event(conn, run_id: UUID, kind: str, payload: dict):
    run = await one(
        conn, "UPDATE runs SET sequence=sequence+1 WHERE id=%s RETURNING sequence,attempt", (run_id,)
    )
    if run is None:
        raise RuntimeError("event run not found")
    await conn.execute(
        "INSERT INTO events(run_id,sequence,kind,payload,attempt) VALUES(%s,%s,%s,%s,%s)",
        (run_id, run["sequence"], kind, Jsonb(payload), run["attempt"]),
    )


class RunStore:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings

    async def create(self, owner_id: UUID, app_id: UUID, body: RunInput, key: str):
        if not key or len(key) > 128:
            forbidden("INVALID_IDEMPOTENCY_KEY", 400)
        hashed = request_hash(body)
        async with self.db.transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(owner_id),))
            app = await owned_app(conn, owner_id, app_id, lock=True)
            existing = await one(
                conn,
                "SELECT * FROM runs WHERE owner_id=%s AND app_id=%s AND idempotency_key=%s",
                (owner_id, app_id, key),
            )
            if existing:
                if existing["request_hash"] != hashed:
                    forbidden("IDEMPOTENCY_CONFLICT", 409)
                return existing
            if app["current_revision"] != body.base_revision:
                forbidden("STALE_REVISION", 409)
            if body.selection and body.selection.revision_id != body.base_revision:
                forbidden("STALE_SELECTION", 409)
            active = await one(
                conn, "SELECT id FROM runs WHERE app_id=%s AND status IN ('queued','running')", (app_id,)
            )
            if active:
                forbidden("APP_BUSY", 409)
            # Durable per-owner admission rate; idempotent replay does not consume it.
            recent = await one(
                conn,
                "SELECT count(*) AS count FROM runs WHERE owner_id=%s "
                "AND created_at>clock_timestamp()-interval '1 hour'",
                (owner_id,),
            )
            if recent["count"] >= 20:
                forbidden("RUN_RATE_LIMIT", 429)
            run_id = uuid4()
            await conn.execute(
                "INSERT INTO runs(id,app_id,owner_id,base_revision,prompt,selection,request_hash,"
                "idempotency_key,status,deadline) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'queued',"
                "clock_timestamp()+make_interval(secs=>%s))",
                (
                    run_id,
                    app_id,
                    owner_id,
                    body.base_revision,
                    body.prompt,
                    Jsonb(body.selection.model_dump(mode="json")) if body.selection else None,
                    hashed,
                    key,
                    self.settings.max_run_seconds,
                ),
            )
            await append_event(conn, run_id, "run.queued", {"type": "queued", "status": "queued"})
            return await one(conn, "SELECT * FROM runs WHERE id=%s", (run_id,))

    async def get(self, owner_id: UUID, app_id: UUID, run_id: UUID):
        async with self.db.transaction() as conn:
            await owned_app(conn, owner_id, app_id)
            row = await one(
                conn,
                "SELECT * FROM runs WHERE id=%s AND app_id=%s AND owner_id=%s",
                (run_id, app_id, owner_id),
            )
            if row is None:
                forbidden("NOT_FOUND", 404)
            return row

    async def events(self, owner_id: UUID, app_id: UUID, run_id: UUID, after: int):
        async with self.db.transaction() as conn:
            await owned_app(conn, owner_id, app_id)
            run = await one(
                conn,
                "SELECT * FROM runs WHERE id=%s AND app_id=%s AND owner_id=%s",
                (run_id, app_id, owner_id),
            )
            if run is None:
                forbidden("NOT_FOUND", 404)
            if after > run["sequence"]:
                forbidden("INVALID_CURSOR", 400)
            rows = await many(
                conn,
                "SELECT * FROM events WHERE run_id=%s AND sequence>%s ORDER BY sequence LIMIT 100",
                (run_id, after),
            )
            return run, [
                {
                    "schema_version": 1,
                    "run_id": str(run_id),
                    "sequence": str(row["sequence"]),
                    "kind": row["kind"],
                    "attempt": row["attempt"],
                    "timestamp": row["created_at"].isoformat(),
                    "payload": row["payload"],
                }
                for row in rows
            ]

    async def cancel(self, owner_id: UUID, app_id: UUID, run_id: UUID):
        async with self.db.transaction() as conn:
            await owned_app(conn, owner_id, app_id, lock=True)
            row = await one(
                conn,
                "SELECT * FROM runs WHERE id=%s AND app_id=%s AND owner_id=%s FOR UPDATE",
                (run_id, app_id, owner_id),
            )
            if row is None:
                forbidden("NOT_FOUND", 404)
            if row["status"] in TERMINAL:
                forbidden("RUN_TERMINAL", 409)
            snapshot = {
                "type": "terminal",
                "status": "cancelled",
                "artifact_revision": None,
                "error": {"code": "CANCELLED", "message": "使用者已取消任務"},
            }
            await conn.execute(
                "UPDATE runs SET status='cancelled',epoch=epoch+1,lease_until=NULL,"
                "error_code='CANCELLED',terminal_snapshot=%s,updated_at=clock_timestamp() WHERE id=%s",
                (Jsonb(snapshot), run_id),
            )
            await append_event(conn, run_id, "run.cancelled", snapshot)
            return await one(conn, "SELECT * FROM runs WHERE id=%s", (run_id,))

    async def claim(self):
        async with self.db.transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(7319402)")
            active = await one(
                conn,
                "SELECT count(*) AS count FROM runs WHERE status='running' AND lease_until>clock_timestamp()",
            )
            if active["count"] >= self.settings.max_active_runs:
                return None
            row = await one(
                conn,
                "SELECT * FROM runs WHERE status='queued' AND deadline>clock_timestamp() "
                "AND attempt<%s ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1",
                (self.settings.max_attempts,),
            )
            if row is None:
                return None
            claimed = await one(
                conn,
                "UPDATE runs SET status='running',attempt=attempt+1,epoch=epoch+1,"
                "lease_until=clock_timestamp()+make_interval(secs=>%s),"
                "updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                (self.settings.lease_seconds, row["id"]),
            )
            await append_event(conn, row["id"], "run.started", {"type": "started", "status": "running"})
            return claimed

    async def heartbeat(self, run_id: UUID, epoch: int) -> bool:
        async with self.db.transaction() as conn:
            row = await one(
                conn,
                "UPDATE runs SET lease_until=clock_timestamp()+make_interval(secs=>%s) "
                "WHERE id=%s AND epoch=%s AND status='running' AND lease_until>clock_timestamp() "
                "AND deadline>clock_timestamp() RETURNING id",
                (self.settings.lease_seconds, run_id, epoch),
            )
            return row is not None

    async def emit(self, run_id: UUID, epoch: int, kind: str, payload: dict) -> bool:
        async with self.db.transaction() as conn:
            row = await one(
                conn,
                "SELECT id FROM runs WHERE id=%s AND epoch=%s AND status='running' "
                "AND lease_until>clock_timestamp() AND deadline>clock_timestamp() FOR UPDATE",
                (run_id, epoch),
            )
            if row is None:
                return False
            await append_event(conn, run_id, kind, payload)
            return True

    async def finish(
        self, run_id: UUID, epoch: int, *, revision: dict | None = None, error_code: str | None = None
    ):
        if (revision is None) == (error_code is None):
            raise ValueError("finish requires exactly one of revision or error")
        async with self.db.transaction() as conn:
            identity = await one(conn, "SELECT app_id,owner_id FROM runs WHERE id=%s", (run_id,))
            if identity is None:
                return False
            app = await owned_app(conn, identity["owner_id"], identity["app_id"], lock=True)
            run = await one(
                conn,
                "SELECT * FROM runs WHERE id=%s AND epoch=%s AND status='running' "
                "AND lease_until>clock_timestamp() AND deadline>clock_timestamp() FOR UPDATE",
                (run_id, epoch),
            )
            if run is None:
                return False
            if app["current_revision"] != run["base_revision"]:
                error_code, revision = "STALE_REVISION", None
            artifact = None
            if revision:
                if not all(revision.get("checks", {}).get(k) is True for k in ("build", "health", "crud")):
                    raise ValueError("revision lacks build/health/CRUD evidence")
                resource_ids = revision.get("resource_ids", [])
                if len(set(resource_ids)) != len(resource_ids):
                    raise ValueError("duplicate revision resources")
                for identity in sorted(resource_ids, key=str):
                    resource = await one(
                        conn, "SELECT * FROM resources WHERE id=%s FOR UPDATE", (identity,),
                    )
                    if (resource is None or resource["app_id"] != app["id"]
                            or resource["run_id"] != run_id or resource["epoch"] != epoch
                            or resource["state"] != "ready" or resource["cleanup_requested"]
                            or resource["retention"] not in {"preview", "app", "revision"}):
                        raise ValueError("revision resource is not eligible for adoption")
                artifact = revision["id"]
                await conn.execute(
                    "INSERT INTO revisions(id,app_id,run_id,parent_id,manifest,app_spec,checks) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        artifact,
                        app["id"],
                        run_id,
                        run["base_revision"],
                        Jsonb(revision["manifest"]),
                        Jsonb(revision["app_spec"]),
                        Jsonb(revision["checks"]),
                    ),
                )
                for identity in resource_ids:
                    await conn.execute(
                        "UPDATE resources SET adopted_revision=%s,updated_at=clock_timestamp() WHERE id=%s",
                        (artifact, identity),
                    )
            status = "failed" if error_code else "succeeded"
            snapshot = {
                "type": "terminal",
                "status": status,
                "artifact_revision": str(artifact) if artifact else None,
                "error": {"code": error_code, "message": "任務未完成，上一個版本仍可使用"}
                if error_code
                else None,
            }
            updated = await one(
                conn,
                "UPDATE runs SET status=%s,artifact_revision=%s,error_code=%s,terminal_snapshot=%s,"
                "lease_until=NULL,updated_at=clock_timestamp() WHERE id=%s AND epoch=%s "
                "AND status='running' AND lease_until>clock_timestamp() AND deadline>clock_timestamp() "
                "RETURNING id",
                (status, artifact, error_code, Jsonb(snapshot), run_id, epoch),
            )
            if updated is None:
                # Roll back the candidate revision insertion, never leave an unpromoted database row.
                raise RuntimeError("lease expired during promotion")
            if artifact:
                await conn.execute(
                    "UPDATE apps SET current_revision=%s,updated_at=clock_timestamp() WHERE id=%s",
                    (artifact, app["id"]),
                )
            await append_event(conn, run_id, "run." + status, snapshot)
            return True

    async def recover(self):
        async with self.db.transaction() as conn:
            candidates = await many(
                conn,
                "SELECT id,app_id,owner_id FROM runs WHERE status IN ('queued','running') "
                "AND (deadline<=clock_timestamp() OR (status='running' AND lease_until<=clock_timestamp()))",
            )
        for item in candidates:
            async with self.db.transaction() as conn:
                app = await one(conn, "SELECT * FROM apps WHERE id=%s FOR UPDATE", (item["app_id"],))
                run = await one(
                    conn,
                    "SELECT * FROM runs WHERE id=%s AND status IN ('queued','running') "
                    "AND (deadline<=clock_timestamp() OR "
                    "(status='running' AND lease_until<=clock_timestamp())) "
                    "FOR UPDATE",
                    (item["id"],),
                )
                if run is None:
                    continue
                now = (await one(conn, "SELECT clock_timestamp() AS now"))["now"]
                if (
                    run["deadline"] > now
                    and run["attempt"] < self.settings.max_attempts
                    and app["deleted_at"] is None
                    and app["current_revision"] == run["base_revision"]
                ):
                    await conn.execute(
                        "UPDATE runs SET status='queued',epoch=epoch+1,lease_until=NULL WHERE id=%s",
                        (run["id"],),
                    )
                    await append_event(
                        conn, run["id"], "run.recovering", {"type": "recovering", "status": "queued"}
                    )
                else:
                    code = "DEADLINE_EXCEEDED" if run["deadline"] <= now else "ATTEMPTS_EXHAUSTED"
                    snapshot = {
                        "type": "terminal",
                        "status": "failed",
                        "artifact_revision": None,
                        "error": {"code": code, "message": "任務已停止"},
                    }
                    await conn.execute(
                        "UPDATE runs SET status='failed',epoch=epoch+1,lease_until=NULL,error_code=%s,"
                        "terminal_snapshot=%s WHERE id=%s",
                        (code, Jsonb(snapshot), run["id"]),
                    )
                    await append_event(conn, run["id"], "run.failed", snapshot)
