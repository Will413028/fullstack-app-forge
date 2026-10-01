import os
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field


def connect():
    return psycopg.connect(os.environ["APP_DATABASE_URL"], row_factory=dict_row, connect_timeout=5)


@asynccontextmanager
async def lifespan(app):
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(7419401)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_versions(version integer PRIMARY KEY)")
        applied = [r["version"] for r in conn.execute("SELECT version FROM schema_versions ORDER BY version")]
        if applied not in ([], [1]):
            raise RuntimeError("generated database schema version incompatible")
        if not applied:
            conn.execute(
                "CREATE TABLE todos(id uuid PRIMARY KEY,title text NOT NULL CHECK(length(title) BETWEEN 1 AND 200),"
                "done boolean NOT NULL DEFAULT false,created_at timestamptz NOT NULL DEFAULT clock_timestamp())"
            )
            conn.execute("INSERT INTO schema_versions(version) VALUES(1)")
    yield


app = FastAPI(title="Generated Todo API", lifespan=lifespan)


class TodoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)


class TodoUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    done: bool | None = None


@app.get("/health")
def health():
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/v1/todos")
def list_todos():
    with connect() as conn:
        return conn.execute("SELECT * FROM todos ORDER BY created_at,id LIMIT 500").fetchall()


@app.post("/v1/todos", status_code=201)
def create_todo(body: TodoCreate):
    with connect() as conn:
        return conn.execute("INSERT INTO todos(id,title) VALUES(%s,%s) RETURNING *", (uuid4(), body.title)).fetchone()


@app.patch("/v1/todos/{identity}")
def update_todo(identity: UUID, body: TodoUpdate):
    if not body.model_fields_set or any(getattr(body, key) is None for key in body.model_fields_set):
        raise HTTPException(422, "Provide a title or done value")
    with connect() as conn:
        row = conn.execute(
            "UPDATE todos SET title=coalesce(%s,title),done=coalesce(%s,done) WHERE id=%s RETURNING *",
            (body.title, body.done, identity),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Todo not found")
        return row


@app.delete("/v1/todos/{identity}", status_code=204)
def delete_todo(identity: UUID):
    with connect() as conn:
        if conn.execute("DELETE FROM todos WHERE id=%s RETURNING id", (identity,)).fetchone() is None:
            raise HTTPException(404, "Todo not found")
    return Response(status_code=204)
