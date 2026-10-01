"""Isolated PostgreSQL role boundaries and fresh-lease completion probe."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

DOCKER = "/opt/homebrew/bin/docker"
IMAGE = "sha256:25a89970a83255ae96484d709005bb35aa71f7455f941bc1634514f31c5d5c62"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    name = "forge-p0-db-" + uuid.uuid4().hex[:12]
    records = []

    def command(argv, check=True):
        result = subprocess.run(argv, text=True, capture_output=True, timeout=40)
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip())
        return result

    def sql(query, db="postgres", user="postgres", check=True):
        return command([DOCKER, "exec", name, "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
                        "-U", user, "-d", db, "-c", query], check=check)

    def record(label, passed):
        records.append({"name": label, "passed": bool(passed)})
        print(label + ": " + str(bool(passed)), flush=True)
        if not passed:
            raise AssertionError(label)

    try:
        command([DOCKER, "run", "--pull=never", "-d", "--name", name, "--label", "forge.scope=p0-db",
                 "--network=none", "--cpus=1", "--memory=256m", "--memory-swap=256m",
                 "-e", "POSTGRES_HOST_AUTH_METHOD=trust", IMAGE])
        for _ in range(80):
            comm = command([DOCKER, "exec", name, "cat", "/proc/1/comm"], check=False)
            if comm.stdout.strip() == "postgres" and command([DOCKER, "exec", name,
                    "pg_isready", "-U", "postgres"], check=False).returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("database not ready")
        sql("CREATE ROLE app_a LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION; "
            "CREATE ROLE app_b LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;")
        for db in ("platform", "a", "b"):
            sql("CREATE DATABASE " + db)
            sql("REVOKE ALL ON DATABASE " + db + " FROM PUBLIC")
        for user, db in (("app_a", "a"), ("app_b", "b")):
            sql(f"GRANT CONNECT ON DATABASE {db} TO {user}")
            sql(f"CREATE TABLE items(id integer PRIMARY KEY, value text); "
                f"REVOKE ALL ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO {user}; "
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON items TO {user};", db=db)
        record("own-app-crud", sql("INSERT INTO items VALUES (1,'ok'); "
                                   "UPDATE items SET value='changed' WHERE id=1; SELECT value FROM items; "
                                   "DELETE FROM items WHERE id=1; SELECT count(*) FROM items;",
                                   db="a", user="app_a").stdout.strip() == "changed\n0")
        record("other-app-connect-denied", sql("SELECT 1", db="b", user="app_a", check=False).returncode != 0)
        record("platform-connect-denied", sql("SELECT 1", db="platform", user="app_a", check=False).returncode != 0)
        record("ddl-denied-runtime-role", sql("CREATE TABLE unauthorized(id int)", db="a",
                                              user="app_a", check=False).returncode != 0)
        record("server-file-read-denied", sql("SELECT pg_read_file('/etc/hostname')", db="a",
                                              user="app_a", check=False).returncode != 0)
        record("role-escalation-denied", sql("SET ROLE postgres", db="a", user="app_a", check=False).returncode != 0)
        sql("CREATE TABLE apps(id int PRIMARY KEY, revision int NOT NULL); "
            "CREATE TABLE runs(id int PRIMARY KEY, app_id int REFERENCES apps(id), base int, "
            "epoch int, status text, lease_until timestamptz); "
            "INSERT INTO apps VALUES (1,0); "
            "INSERT INTO runs VALUES(1,1,0,1,'running',clock_timestamp()-interval '1 second');")
        completion = ("UPDATE runs r SET status='succeeded' FROM apps a WHERE r.id=1 AND a.id=r.app_id "
                      "AND a.revision=r.base AND r.epoch=1 AND r.status='running' "
                      "AND r.lease_until>clock_timestamp() RETURNING r.id")
        record("expired-unreclaimed-lease-cannot-complete", sql(completion).stdout.strip() == "")
        sql("UPDATE runs SET lease_until=clock_timestamp()+interval '60 seconds'; UPDATE apps SET revision=1;")
        record("stale-base-cannot-complete", sql(completion).stdout.strip() == "")
        sql("UPDATE apps SET revision=0; UPDATE runs SET epoch=2;")
        record("stale-epoch-cannot-complete", sql(completion).stdout.strip() == "")
        sql("UPDATE runs SET epoch=1;")
        record("fresh-lease-base-epoch-completes", sql(completion).stdout.strip() == "1")
    finally:
        cleanup = command([DOCKER, "rm", "-f", "-v", name], check=False).returncode == 0
        args.output.write_text(json.dumps({"image": IMAGE, "checks": records, "cleanup": cleanup}, indent=2) + "\n")
    if not cleanup:
        raise RuntimeError("owned DB cleanup failed")


if __name__ == "__main__":
    main()
