import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from argon2.exceptions import VerificationError
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg.errors import UniqueViolation

from forge.config import Settings
from forge.config import settings as default_settings
from forge.db import Database, many, one
from forge.models import AppInput, Credentials, RunInput
from forge.runs import TERMINAL, RunStore, owned_app
from forge.security import PASSWORDS, SESSION_COOKIE, digest, forbidden, new_token

CSRF_COOKIE = "forge_csrf"


def public_user(row):
    return {"id": str(row["id"]), "username": row["username"], "role": row["role"]}


def create_app(settings: Settings = default_settings, database: Database | None = None):
    owns_database = database is None
    db = database or Database(settings)
    runs = RunStore(db, settings)

    @asynccontextmanager
    async def lifespan(app):
        if owns_database:
            await db.open()
        yield
        if owns_database:
            await db.close()

    app = FastAPI(title="Fullstack App Forge", version="0.1.0", lifespan=lifespan)
    app.state.db, app.state.runs = db, runs

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic error input can contain a submitted password. Return safe metadata only.
        errors = [
            {"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]} for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": {"code": "INVALID_INPUT", "errors": errors}})

    @app.middleware("http")
    async def security_headers(request, call_next):
        if request.method in ("POST", "PATCH", "PUT", "DELETE"):
            if request.headers.get("origin") != settings.platform_origin:
                return JSONResponse(status_code=403, content={"detail": {"code": "INVALID_ORIGIN"}})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    async def authenticate(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            forbidden("UNAUTHENTICATED", 401)
        async with db.transaction() as conn:
            user = await one(
                conn,
                "SELECT u.id,u.username,u.role,s.csrf_hash FROM sessions s "
                "JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s "
                "AND s.expires_at>clock_timestamp() AND NOT u.disabled",
                (digest(token),),
            )
        if not user:
            forbidden("UNAUTHENTICATED", 401)
        return user

    async def writing_user(request: Request, user=Depends(authenticate)):
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not hmac.compare_digest(digest(csrf), user["csrf_hash"]):
            forbidden("INVALID_CSRF")
        return user

    async def auth_rate(request: Request, username: str):
        address = request.client.host if request.client else "unknown"
        bucket = digest(address + ":" + username.casefold())
        async with db.transaction() as conn:
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))", (bucket,))
            recent = await one(
                conn,
                "SELECT count(*) AS count FROM auth_attempts WHERE bucket=%s "
                "AND created_at>clock_timestamp()-interval '15 minutes'",
                (bucket,),
            )
            if recent["count"] >= 10:
                forbidden("AUTH_RATE_LIMIT", 429)
            await conn.execute("INSERT INTO auth_attempts(bucket) VALUES(%s)", (bucket,))

    async def issue_session(response: Response, user):
        token, csrf = new_token(), new_token()
        async with db.transaction() as conn:
            await conn.execute(
                "INSERT INTO sessions(token_hash,user_id,csrf_hash,expires_at) "
                "VALUES(%s,%s,%s,clock_timestamp()+make_interval(hours=>%s))",
                (digest(token), user["id"], digest(csrf), settings.session_hours),
            )
        for name, value, httponly in ((SESSION_COOKIE, token, True), (CSRF_COOKIE, csrf, False)):
            response.set_cookie(
                name,
                value,
                max_age=settings.session_hours * 3600,
                path="/",
                secure=settings.secure_cookies,
                httponly=httponly,
                samesite="strict",
            )
        return {"user": public_user(user), "csrf_token": csrf}

    @app.get("/health")
    async def health():
        async with db.transaction() as conn:
            await one(conn, "SELECT 1")
        return {"status": "ok"}

    @app.post("/v1/auth/register", status_code=201)
    async def register(body: Credentials, request: Request, response: Response):
        await auth_rate(request, body.username)
        password_hash = await asyncio.to_thread(PASSWORDS.hash, body.password)
        try:
            async with db.transaction() as conn:
                await conn.execute("SELECT pg_advisory_xact_lock(7319403)")
                count = await one(conn, "SELECT count(*) AS count FROM users")
                user = await one(
                    conn,
                    "INSERT INTO users(id,username,password_hash,role) VALUES(%s,%s,%s,%s) "
                    "RETURNING id,username,role",
                    (
                        uuid4(),
                        body.username.casefold(),
                        password_hash,
                        "admin" if count["count"] == 0 else "user",
                    ),
                )
        except UniqueViolation:
            forbidden("USERNAME_TAKEN", 409)
        return await issue_session(response, user)

    @app.post("/v1/auth/login")
    async def login(body: Credentials, request: Request, response: Response):
        await auth_rate(request, body.username)
        async with db.transaction() as conn:
            user = await one(
                conn, "SELECT * FROM users WHERE username=%s AND NOT disabled", (body.username.casefold(),)
            )
        if user is None:
            # Perform the same password work for unknown users without a fixed published account.
            await asyncio.to_thread(PASSWORDS.hash, body.password)
            forbidden("INVALID_LOGIN", 401)
        try:
            await asyncio.to_thread(PASSWORDS.verify, user["password_hash"], body.password)
        except VerificationError:
            forbidden("INVALID_LOGIN", 401)
        return await issue_session(response, user)

    @app.get("/v1/auth/session")
    async def session(request: Request, user=Depends(authenticate)):
        csrf = request.cookies.get(CSRF_COOKIE, "")
        if not csrf or not hmac.compare_digest(digest(csrf), user["csrf_hash"]):
            forbidden("INVALID_CSRF")
        return {"user": public_user(user), "csrf_token": csrf}

    @app.post("/v1/auth/logout", status_code=204)
    async def logout(request: Request, response: Response, user=Depends(writing_user)):
        async with db.transaction() as conn:
            await conn.execute(
                "DELETE FROM sessions WHERE token_hash=%s", (digest(request.cookies[SESSION_COOKIE]),)
            )
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")

    @app.get("/v1/apps")
    async def list_apps(user=Depends(authenticate)):
        async with db.transaction() as conn:
            return await many(
                conn,
                "SELECT * FROM apps WHERE owner_id=%s AND deleted_at IS NULL ORDER BY updated_at DESC",
                (user["id"],),
            )

    @app.post("/v1/apps", status_code=201)
    async def create_application(body: AppInput, user=Depends(writing_user)):
        async with db.transaction() as conn:
            return await one(
                conn,
                "INSERT INTO apps(id,owner_id,name,description) VALUES(%s,%s,%s,%s) RETURNING *",
                (uuid4(), user["id"], body.name, body.description),
            )

    @app.get("/v1/apps/{app_id}")
    async def get_application(app_id: UUID, user=Depends(authenticate)):
        async with db.transaction() as conn:
            return await owned_app(conn, user["id"], app_id)

    @app.patch("/v1/apps/{app_id}")
    async def update_application(app_id: UUID, body: AppInput, user=Depends(writing_user)):
        async with db.transaction() as conn:
            await owned_app(conn, user["id"], app_id, lock=True)
            return await one(
                conn,
                "UPDATE apps SET name=%s,description=%s,updated_at=clock_timestamp() WHERE id=%s RETURNING *",
                (body.name, body.description, app_id),
            )

    @app.delete("/v1/apps/{app_id}", status_code=204)
    async def delete_application(app_id: UUID, user=Depends(writing_user)):
        async with db.transaction() as conn:
            await owned_app(conn, user["id"], app_id, lock=True)
            active = await one(
                conn, "SELECT id FROM runs WHERE app_id=%s AND status IN ('queued','running')", (app_id,)
            )
            if active:
                forbidden("APP_BUSY", 409)
            await conn.execute(
                "UPDATE apps SET deleted_at=clock_timestamp(),public=false,featured=false WHERE id=%s",
                (app_id,),
            )

    @app.get("/v1/apps/{app_id}/runs")
    async def list_runs(app_id: UUID, user=Depends(authenticate)):
        async with db.transaction() as conn:
            await owned_app(conn, user["id"], app_id)
            return await many(
                conn,
                "SELECT * FROM runs WHERE app_id=%s AND owner_id=%s ORDER BY created_at DESC",
                (app_id, user["id"]),
            )

    @app.post("/v1/apps/{app_id}/runs", status_code=202)
    async def create_run(
        app_id: UUID, body: RunInput, idempotency_key: str = Header(), user=Depends(writing_user)
    ):
        return await runs.create(user["id"], app_id, body, idempotency_key)

    @app.get("/v1/apps/{app_id}/runs/{run_id}")
    async def get_run(app_id: UUID, run_id: UUID, user=Depends(authenticate)):
        return await runs.get(user["id"], app_id, run_id)

    @app.post("/v1/apps/{app_id}/runs/{run_id}/cancel")
    async def cancel_run(app_id: UUID, run_id: UUID, user=Depends(writing_user)):
        return await runs.cancel(user["id"], app_id, run_id)

    @app.get("/v1/apps/{app_id}/runs/{run_id}/events")
    async def events(
        app_id: UUID,
        run_id: UUID,
        request: Request,
        last_event_id: str = Header(default="0"),
        user=Depends(authenticate),
    ):
        if not last_event_id.isascii() or not last_event_id.isdecimal() or len(last_event_id) > 19:
            forbidden("INVALID_CURSOR", 400)
        cursor = int(last_event_id)
        initial_run, initial_events = await runs.events(user["id"], app_id, run_id, cursor)

        async def stream():
            nonlocal cursor
            run, batch = initial_run, initial_events
            while True:
                if await request.is_disconnected():
                    return
                for event in batch:
                    cursor = int(event["sequence"])
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"id: {event['sequence']}\nevent: forge\ndata: {data}\n\n"
                if run["status"] in TERMINAL and cursor >= run["sequence"]:
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)
                try:
                    await authenticate(request)
                    run, batch = await runs.events(user["id"], app_id, run_id, cursor)
                except HTTPException:
                    return

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    return app


app = create_app()
