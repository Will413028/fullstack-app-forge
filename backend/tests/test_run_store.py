import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from psycopg import AsyncConnection, OperationalError

from forge.config import Settings
from forge.db import Database
from forge.main import create_app
from forge.models import RunInput
from forge.resources import ResourceFenceError, ResourceStore, SettledDeleteFailure
from forge.runs import RunStore

pytestmark = pytest.mark.asyncio(loop_scope="module")
PG = "postgres@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def database():
    docker = shutil.which("docker")
    if not docker:
        pytest.fail("Docker is required for real PostgreSQL store tests")
    name = "forge-store-test-" + uuid4().hex[:12]

    def command(*args, check=True):
        result = subprocess.run([docker, *args], capture_output=True, timeout=60, check=check)
        if args[0] == "logs":
            return (result.stdout + result.stderr).decode(errors="replace").strip()
        return result.stdout.decode().strip()

    db = None
    try:
        command(
            "run",
            "--pull=never",
            "-d",
            "--name",
            name,
            "--cpus=.5",
            "--memory=256m",
            "--memory-swap=256m",
            "--pids-limit=64",
            "-p",
            "127.0.0.1::5432",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=forge",
            PG,
        )
        port = command("port", name, "5432/tcp").rsplit(":", 1)[1]
        settings = Settings(database_url=f"postgresql://postgres@127.0.0.1:{port}/forge")
        deadline = asyncio.get_running_loop().time() + 240
        while asyncio.get_running_loop().time() < deadline:
            try:
                # Probe the same host TCP route as the API pool. initdb's temporary
                # Unix-socket server cannot satisfy this connection.
                async with asyncio.timeout(5):
                    async with await AsyncConnection.connect(
                        settings.database_url, connect_timeout=3
                    ) as conn:
                        await conn.execute("SELECT 1")
                break
            except (OperationalError, TimeoutError):
                await asyncio.sleep(0.5)
        else:
            diagnostics = {
                "container": name,
                "state": command("inspect", name, "--format", "{{json .State}}", check=False),
                "postgres_log": command("logs", "--tail", "50", name, check=False),
            }
            attachment = Path(__file__).resolve().parents[2] / "docs/plans/2026-10-01-full-rebuild"
            (attachment / f"{name}-readiness.json").write_text(json.dumps(diagnostics, indent=2))
            pytest.fail("isolated PostgreSQL readiness deadline")
        db = Database(settings)
        await db.open()
        yield db, settings
    finally:
        if db:
            await db.close()
        result = subprocess.run([docker, "rm", "-f", "-v", name], capture_output=True, timeout=60)
        if result.returncode != 0:
            absent = subprocess.run(
                [docker, "inspect", name, "--format", "{{.Id}}"], capture_output=True, timeout=30
            )
            assert absent.returncode != 0 and b"No such" in absent.stderr, (
                "owned PostgreSQL cleanup unverified"
            )


@pytest_asyncio.fixture(loop_scope="module")
async def fixture(database):
    db, settings = database
    owner, other, app = uuid4(), uuid4(), uuid4()
    async with db.transaction() as conn:
        for identity in (owner, other):
            await conn.execute(
                "INSERT INTO users(id,username,password_hash) VALUES(%s,%s,'fixture-hash')",
                (identity, "fixture-" + identity.hex),
            )
        await conn.execute("INSERT INTO apps(id,owner_id,name) VALUES(%s,%s,'Fixture app')", (app, owner))
    return RunStore(db, settings), owner, other, app


def revision():
    return {
        "id": uuid4(),
        "manifest": {"files": ["app/page.tsx"]},
        "app_spec": {"title": "Store predicate fixture"},
        "checks": {"build": True, "health": True, "crud": True},
    }


async def test_retry_same_key_returns_original_run(fixture):
    store, owner, _, app = fixture
    body = RunInput(prompt="todo")
    first = await store.create(owner, app, body, "key")
    second = await store.create(owner, app, body, "key")
    assert second["id"] == first["id"]
    run, events = await store.events(owner, app, first["id"], 0)
    assert len(events) == 1 and events[0]["kind"] == "run.queued" and events[0]["attempt"] == 0
    assert run["attempt"] == 0
    await store.cancel(owner, app, first["id"])


async def test_changed_payload_conflicts(fixture):
    store, owner, _, app = fixture
    first = await store.create(owner, app, RunInput(prompt="todo"), "key")
    with pytest.raises(HTTPException) as exc:
        await store.create(owner, app, RunInput(prompt="crm"), "key")
    assert exc.value.status_code == 409 and exc.value.detail["code"] == "IDEMPOTENCY_CONFLICT"
    await store.cancel(owner, app, first["id"])


async def test_owner_cannot_subscribe_other_run(fixture):
    store, owner, other, app = fixture
    run = await store.create(owner, app, RunInput(prompt="todo"), "key")
    with pytest.raises(HTTPException) as exc:
        await store.events(other, app, run["id"], 0)
    assert exc.value.status_code == 404
    await store.cancel(owner, app, run["id"])


async def test_active_run_conflict(fixture):
    store, owner, _, app = fixture
    run = await store.create(owner, app, RunInput(prompt="todo"), "first")
    with pytest.raises(HTTPException) as exc:
        await store.create(owner, app, RunInput(prompt="notes"), "second")
    assert exc.value.detail["code"] == "APP_BUSY"
    await store.cancel(owner, app, run["id"])


async def test_expired_lease_cannot_promote(fixture):
    store, owner, _, app = fixture
    run = await store.create(owner, app, RunInput(prompt="todo"), "key")
    claimed = await store.claim()
    assert claimed["id"] == run["id"]
    async with store.db.transaction() as conn:
        await conn.execute(
            "UPDATE runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (run["id"],)
        )
    assert await store.finish(run["id"], claimed["epoch"], revision=revision()) is False
    assert await store.heartbeat(run["id"], claimed["epoch"]) is False
    await store.recover()
    claimed2 = await store.claim()
    assert claimed2["attempt"] == 2 and claimed2["epoch"] > claimed["epoch"]
    assert await store.finish(run["id"], claimed["epoch"], revision=revision()) is False
    assert await store.finish(run["id"], claimed2["epoch"], error_code="FIXTURE_FAILED") is True


async def test_cancel_cannot_be_overwritten_by_completion(fixture):
    store, owner, _, app = fixture
    run = await store.create(owner, app, RunInput(prompt="todo"), "key")
    claimed = await store.claim()
    await store.cancel(owner, app, run["id"])
    assert await store.finish(run["id"], claimed["epoch"], revision=revision()) is False
    current = await store.get(owner, app, run["id"])
    assert current["status"] == "cancelled" and current["artifact_revision"] is None


async def test_success_requires_evidence_and_promotes_atomically(fixture):
    store, owner, _, app = fixture
    run = await store.create(owner, app, RunInput(prompt="todo"), "key")
    claimed = await store.claim()
    candidate = revision()
    candidate["checks"]["crud"] = False
    with pytest.raises(ValueError, match="evidence"):
        await store.finish(run["id"], claimed["epoch"], revision=candidate)
    candidate["checks"]["crud"] = True
    assert await store.finish(run["id"], claimed["epoch"], revision=candidate)
    current = await store.get(owner, app, run["id"])
    assert current["status"] == "succeeded" and current["artifact_revision"] == candidate["id"]
    with pytest.raises(HTTPException) as exc:
        await store.create(owner, app, RunInput(prompt="modify"), "new")
    assert exc.value.detail["code"] == "STALE_REVISION"
    next_run = await store.create(owner, app, RunInput(prompt="modify", base_revision=candidate["id"]), "new")
    await store.cancel(owner, app, next_run["id"])


async def test_sse_replay_has_no_create_side_effect(fixture):
    store, owner, _, app = fixture
    run = await store.create(owner, app, RunInput(prompt="todo"), "key")
    _, first = await store.events(owner, app, run["id"], 0)
    _, second = await store.events(owner, app, run["id"], int(first[-1]["sequence"]))
    assert second == []
    with pytest.raises(HTTPException) as exc:
        await store.events(owner, app, run["id"], 2)
    assert exc.value.detail["code"] == "INVALID_CURSOR"
    await store.cancel(owner, app, run["id"])


async def test_http_auth_app_run_replay_and_logout(database):
    db, settings = database
    transport = ASGITransport(app=create_app(settings, database=db))
    async with AsyncClient(transport=transport, base_url=settings.platform_origin) as client:
        origin = {"Origin": settings.platform_origin}
        credentials = {"username": "api-" + uuid4().hex[:12], "password": "isolated-test-password"}
        assert (await client.post("/v1/auth/register", json=credentials)).status_code == 403
        registered = await client.post("/v1/auth/register", json=credentials, headers=origin)
        assert registered.status_code == 201
        csrf = registered.json()["csrf_token"]
        writing = {**origin, "X-CSRF-Token": csrf}
        assert (await client.get("/v1/auth/session")).status_code == 200
        assert (await client.post("/v1/apps", json={"name": "Todo"}, headers=origin)).status_code == 403
        created = await client.post("/v1/apps", json={"name": "Todo"}, headers=writing)
        assert created.status_code == 201
        app_id = created.json()["id"]
        started = await client.post(
            f"/v1/apps/{app_id}/runs",
            json={"prompt": "todo"},
            headers={**writing, "Idempotency-Key": "http-fixture"},
        )
        assert started.status_code == 202
        run_id = started.json()["id"]
        cancelled = await client.post(f"/v1/apps/{app_id}/runs/{run_id}/cancel", headers=writing)
        assert cancelled.status_code == 200
        replay = await client.get(f"/v1/apps/{app_id}/runs/{run_id}/events", headers={"Last-Event-ID": "1"})
        assert replay.status_code == 200
        assert "run.cancelled" in replay.text and "run.queued" not in replay.text
        listed = await client.get(f"/v1/apps/{app_id}/runs")
        assert len(listed.json()) == 1
        assert (await client.delete(f"/v1/apps/{app_id}", headers=writing)).status_code == 204
        assert (await client.get(f"/v1/apps/{app_id}")).status_code == 404
        assert (await client.post("/v1/auth/logout", headers=writing)).status_code == 204
        assert (await client.get("/v1/auth/session")).status_code == 401
        assert (await client.post("/v1/auth/login", json=credentials, headers=origin)).status_code == 200


async def test_http_cross_owner_and_password_error_redaction(database):
    db, settings = database
    transport = ASGITransport(app=create_app(settings, database=db))
    origin = {"Origin": settings.platform_origin}
    async with AsyncClient(transport=transport, base_url=settings.platform_origin) as first:
        invalid = await first.post(
            "/v1/auth/register", json={"username": "valid-name", "password": "short"}, headers=origin
        )
        assert invalid.status_code == 422
        assert all(set(error) == {"loc", "type", "msg"} for error in invalid.json()["detail"]["errors"])
        registered = await first.post(
            "/v1/auth/register",
            json={"username": "first-" + uuid4().hex[:10], "password": "isolated-test-password"},
            headers=origin,
        )
        assert registered.status_code == 201
        writing = {**origin, "X-CSRF-Token": registered.json()["csrf_token"]}
        created = await first.post("/v1/apps", json={"name": "Private"}, headers=writing)
        assert created.status_code == 201
        app_id = created.json()["id"]
        async with AsyncClient(transport=transport, base_url=settings.platform_origin) as second:
            registered2 = await second.post(
                "/v1/auth/register",
                json={"username": "second-" + uuid4().hex[:10], "password": "isolated-test-password"},
                headers=origin,
            )
            assert registered2.status_code == 201
            assert (await second.get(f"/v1/apps/{app_id}")).status_code == 404
            headers = {**origin, "X-CSRF-Token": registered2.json()["csrf_token"], "Idempotency-Key": "evil"}
            assert (
                await second.post(f"/v1/apps/{app_id}/runs", json={"prompt": "take over"}, headers=headers)
            ).status_code == 404


async def test_platform_migrations_reopen_without_reapplying(database):
    db, settings = database
    async with db.transaction() as conn:
        row = await (await conn.execute("SELECT applied_at FROM schema_versions WHERE version=1")).fetchone()
        original = row["applied_at"]
    reopened = Database(settings)
    try:
        await reopened.open()
        async with reopened.transaction() as conn:
            row = await (
                await conn.execute("SELECT applied_at FROM schema_versions WHERE version=1")
            ).fetchone()
            assert row["applied_at"] == original
    finally:
        await reopened.close()


async def test_platform_rejects_future_database_version(database):
    db, settings = database
    async with db.transaction() as conn:
        await conn.execute("INSERT INTO schema_versions(version) VALUES(3)")
    incompatible = Database(settings)
    try:
        with pytest.raises(RuntimeError, match="incompatible"):
            await incompatible.open()
        assert incompatible.pool.closed
    finally:
        await incompatible.close()
        async with db.transaction() as conn:
            await conn.execute("DELETE FROM schema_versions WHERE version=3")


async def resource_fixture(fixture, retention="run"):
    store, owner, _, app = fixture
    run = await store.create(owner, app, RunInput(prompt="resource fixture"), "resource")
    claimed = await store.claim()
    assert claimed["id"] == run["id"]
    resources = ResourceStore(store.db)
    row = await resources.reserve(run["id"], claimed["epoch"], slot="db", kind="volume", retention=retention)
    return store, resources, owner, app, claimed, row


async def test_resources_cancel_during_create_retains_intent_until_ack(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture)
    creating = await resources.begin_create(row["id"], run["epoch"])
    await store.cancel(owner, app, run["id"])
    assert await resources.claim_cleanup() == []
    assert await resources.outcome_unknown(row["id"], creating["operation_id"])
    assert await resources.claim_cleanup() == []
    assert await resources.complete_create(row["id"], creating["operation_id"])
    cleanup = await resources.claim_cleanup()
    assert len(cleanup) == 1 and cleanup[0]["id"] == row["id"]
    assert await resources.complete_delete(row["id"], cleanup[0]["operation_id"])


async def test_resource_reconciler_tokens_fence_duplicate_and_unknown_delete(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture)
    creating = await resources.begin_create(row["id"], run["epoch"])
    assert not await resources.complete_create(row["id"], uuid4())
    assert await resources.complete_create(row["id"], creating["operation_id"])
    await store.cancel(owner, app, run["id"])
    first, second = await asyncio.gather(resources.claim_cleanup(), resources.claim_cleanup())
    assert len(first) + len(second) == 1
    deleting = (first + second)[0]
    assert not await resources.complete_delete(row["id"], creating["operation_id"])
    assert await resources.outcome_unknown(row["id"], deleting["operation_id"])
    assert await resources.claim_cleanup() == []
    assert not await resources.delete_failed(row["id"], deleting["operation_id"])
    assert await resources.complete_delete(row["id"], deleting["operation_id"])


async def test_reserved_resource_never_created_after_old_epoch(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture)
    same = await resources.reserve(run["id"], run["epoch"], slot="db", kind="volume")
    assert same["external_name"] == row["external_name"]
    async with store.db.transaction() as conn:
        await conn.execute("UPDATE runs SET epoch=epoch+1 WHERE id=%s", (run["id"],))
    with pytest.raises(ResourceFenceError):
        await resources.begin_create(row["id"], run["epoch"])
    assert await resources.claim_cleanup() == []
    async with store.db.transaction() as conn:
        cursor = await conn.execute("SELECT state FROM resources WHERE id=%s", (row["id"],))
        current = await cursor.fetchone()
        assert current["state"] == "deleted"
    await store.cancel(owner, app, run["id"])


async def test_promoted_resource_survives_run_and_tombstone_requests_cleanup(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture, "app")
    creating = await resources.begin_create(row["id"], run["epoch"])
    assert await resources.complete_create(row["id"], creating["operation_id"])
    candidate = revision()
    candidate["resource_ids"] = [row["id"]]
    assert await store.finish(run["id"], run["epoch"], revision=candidate)
    assert await resources.claim_cleanup() == []
    async with store.db.transaction() as conn:
        await conn.execute("UPDATE apps SET deleted_at=clock_timestamp() WHERE id=%s", (app,))
    assert await resources.claim_cleanup() == []
    async with store.db.transaction() as conn:
        await conn.execute(
            "UPDATE apps SET deleted_at=clock_timestamp()-interval '8 days' WHERE id=%s", (app,),
        )
    deleting = await resources.claim_cleanup()
    assert len(deleting) == 1 and deleting[0]["id"] == row["id"]
    assert await resources.complete_delete(row["id"], deleting[0]["operation_id"])


async def test_unpromoted_app_resource_and_temporary_success_resource_are_collected(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture, "app")
    temp = await resources.reserve(run["id"], run["epoch"], slot="builder", kind="container")
    for item in (row, temp):
        creating = await resources.begin_create(item["id"], run["epoch"])
        assert await resources.complete_create(item["id"], creating["operation_id"])
    assert await store.finish(run["id"], run["epoch"], revision=revision())
    deleting = await resources.claim_cleanup()
    assert {item["id"] for item in deleting} == {row["id"], temp["id"]}
    for item in deleting:
        assert await resources.complete_delete(item["id"], item["operation_id"])


async def test_resource_adoption_rejects_cleanup_and_rolls_back_revision(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture, "revision")
    creating = await resources.begin_create(row["id"], run["epoch"])
    assert await resources.complete_create(row["id"], creating["operation_id"])
    await resources.request_cleanup(row["id"])
    candidate = revision()
    candidate["resource_ids"] = [row["id"]]
    with pytest.raises(ValueError, match="eligible"):
        await store.finish(run["id"], run["epoch"], revision=candidate)
    async with store.db.transaction() as conn:
        cursor = await conn.execute("SELECT id FROM revisions WHERE id=%s", (candidate["id"],))
        assert await cursor.fetchone() is None
    await store.cancel(owner, app, run["id"])
    for item in await resources.claim_cleanup():
        assert await resources.complete_delete(item["id"], item["operation_id"])


async def test_reconciler_unknown_is_not_retried_and_settled_failure_can_retry(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture)
    creating = await resources.begin_create(row["id"], run["epoch"])
    assert await resources.complete_create(row["id"], creating["operation_id"])
    await store.cancel(owner, app, run["id"])
    calls = []

    async def unknown(item):
        calls.append(item["id"])
        raise TimeoutError("fixture unknown Docker result")

    result = await resources.reconcile(unknown)
    assert result == {"deleted": [], "retry": [], "unknown": [row["id"]]}
    assert await resources.reconcile(unknown) == {"deleted": [], "retry": [], "unknown": []}
    assert calls == [row["id"]]
    unresolved = await resources.unresolved()
    operation = next(item["operation_id"] for item in unresolved if item["id"] == row["id"])
    assert await resources.complete_delete(row["id"], operation)


async def test_settled_remove_failure_uses_new_token_and_does_not_accept_old_ack(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture)
    creating = await resources.begin_create(row["id"], run["epoch"])
    assert await resources.complete_create(row["id"], creating["operation_id"])
    await store.cancel(owner, app, run["id"])
    tokens = []

    async def settled_failure(item):
        tokens.append(item["operation_id"])
        raise SettledDeleteFailure("fixture settled removal error")

    assert (await resources.reconcile(settled_failure))["retry"] == [row["id"]]

    async def success(item):
        assert item["operation_id"] != tokens[0]
        assert not await resources.complete_delete(row["id"], tokens[0])

    assert (await resources.reconcile(success))["deleted"] == [row["id"]]


async def test_settled_create_absence_terminates_unknown_without_delete(fixture):
    store, resources, owner, app, run, row = await resource_fixture(fixture)
    creating = await resources.begin_create(row["id"], run["epoch"])
    assert await resources.outcome_unknown(row["id"], creating["operation_id"])
    await store.cancel(owner, app, run["id"])
    assert not await resources.complete_create_absent(row["id"], uuid4())
    assert await resources.complete_create_absent(row["id"], creating["operation_id"])
    assert await resources.claim_cleanup() == []
    assert not await resources.complete_create(row["id"], creating["operation_id"])
