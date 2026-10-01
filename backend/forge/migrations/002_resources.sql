ALTER TABLE runs ADD CONSTRAINT runs_identity_app UNIQUE(id, app_id);
ALTER TABLE revisions ADD CONSTRAINT revisions_identity_app UNIQUE(id, app_id);
CREATE TABLE resources (
    id uuid PRIMARY KEY,
    app_id uuid NOT NULL REFERENCES apps(id),
    run_id uuid NOT NULL,
    epoch bigint NOT NULL CHECK(epoch > 0),
    slot text NOT NULL CHECK(slot ~ '^[a-z][a-z0-9-]{0,47}$'),
    kind text NOT NULL CHECK(kind IN ('container','volume','network','loop-scope')),
    retention text NOT NULL CHECK(retention IN ('run','preview','app','revision')),
    adopted_revision uuid,
    external_name text UNIQUE NOT NULL,
    state text NOT NULL DEFAULT 'reserved'
        CHECK(state IN ('reserved','creating','ready','deleting','unknown','deleted')),
    operation_id uuid,
    operation_action text CHECK(operation_action IN ('create','delete')),
    cleanup_requested boolean NOT NULL DEFAULT false,
    error_code text CHECK(error_code IN ('OUTCOME_UNKNOWN','DELETE_FAILED')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(run_id, epoch, slot),
    FOREIGN KEY(run_id, app_id) REFERENCES runs(id, app_id),
    FOREIGN KEY(adopted_revision, app_id) REFERENCES revisions(id, app_id),
    CHECK((state IN ('creating','deleting','unknown')) = (operation_id IS NOT NULL)),
    CHECK((operation_id IS NOT NULL) = (operation_action IS NOT NULL)),
    CHECK(state != 'creating' OR operation_action = 'create'),
    CHECK(state != 'deleting' OR operation_action = 'delete')
);
CREATE INDEX resources_reconcile ON resources(state, updated_at) WHERE state != 'deleted';
CREATE INDEX resources_app ON resources(app_id) WHERE state != 'deleted';
