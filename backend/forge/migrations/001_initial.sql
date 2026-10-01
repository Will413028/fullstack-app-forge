CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    username text UNIQUE NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
    disabled boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS auth_attempts (
    bucket text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS auth_attempts_bucket ON auth_attempts(bucket, created_at);
CREATE TABLE IF NOT EXISTS apps (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL REFERENCES users(id),
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    current_revision uuid,
    featured boolean NOT NULL DEFAULT false,
    public boolean NOT NULL DEFAULT false,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS apps_owner ON apps(owner_id, created_at);
CREATE TABLE IF NOT EXISTS runs (
    id uuid PRIMARY KEY,
    app_id uuid NOT NULL REFERENCES apps(id),
    owner_id uuid NOT NULL REFERENCES users(id),
    base_revision uuid,
    prompt text NOT NULL,
    selection jsonb,
    request_hash text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
    attempt integer NOT NULL DEFAULT 0,
    epoch bigint NOT NULL DEFAULT 0,
    lease_until timestamptz,
    deadline timestamptz NOT NULL,
    sequence bigint NOT NULL DEFAULT 0,
    artifact_revision uuid,
    error_code text,
    terminal_snapshot jsonb,
    usage jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(owner_id, app_id, idempotency_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS runs_app_active ON runs(app_id) WHERE status IN ('queued','running');
CREATE INDEX IF NOT EXISTS runs_queue ON runs(status, created_at);
CREATE TABLE IF NOT EXISTS events (
    run_id uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    sequence bigint NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    attempt integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(run_id, sequence)
);
CREATE TABLE IF NOT EXISTS revisions (
    id uuid PRIMARY KEY,
    app_id uuid NOT NULL REFERENCES apps(id),
    run_id uuid REFERENCES runs(id),
    parent_id uuid REFERENCES revisions(id),
    manifest jsonb NOT NULL,
    app_spec jsonb NOT NULL,
    checks jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS deployments (
    id uuid PRIMARY KEY,
    app_id uuid NOT NULL REFERENCES apps(id),
    revision_id uuid NOT NULL REFERENCES revisions(id),
    status text NOT NULL CHECK(status IN ('starting','ready','failed','stopped')),
    share_id uuid UNIQUE NOT NULL,
    public boolean NOT NULL DEFAULT false,
    frontend_url text,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS assets (
    id uuid PRIMARY KEY,
    app_id uuid NOT NULL REFERENCES apps(id),
    name text NOT NULL,
    media_type text NOT NULL,
    sha256 text NOT NULL,
    attribution text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
