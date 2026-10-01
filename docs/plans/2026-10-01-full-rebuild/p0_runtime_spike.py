"""Probe PostgreSQL queue semantics and constrained Docker execution."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path
import subprocess
import time
import uuid

DOCKER = "/opt/homebrew/bin/docker"
PG_IMAGE = "sha256:25a89970a83255ae96484d709005bb35aa71f7455f941bc1634514f31c5d5c62"
PY_IMAGE = "sha256:75496575cd8e3aeb3fe561f0384f661d490c14770eda935d2302d61ca20a0b2d"


def command(args, *, text=None, timeout=30, check=True):
    result = subprocess.run(args, input=text, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {result.stderr.strip()}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    owned = set()
    records = []
    prefix = "forge-p0-" + uuid.uuid4().hex[:10]

    def record(name, passed, evidence):
        records.append({"name": name, "passed": bool(passed), "evidence": evidence})
        if not passed:
            raise AssertionError(name)

    def start(name, flags, image, argv):
        owned.add(name)
        result = command([DOCKER, "run", "--pull=never", "-d", "--name", name,
                          "--label", "forge.scope=p0-spike", *flags, image, *argv])
        return result.stdout.strip()

    def sql(query):
        return command([DOCKER, "exec", "-i", prefix + "-pg", "psql", "-X", "-qAt",
                        "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "postgres"],
                       text=query).stdout.strip()

    def sandbox(code, *, memory="64m"):
        name = prefix + "-" + uuid.uuid4().hex[:6]
        start(name, ["--network=none", "--read-only", "--user", "65534:65534",
                     "--cap-drop=ALL", "--security-opt", "no-new-privileges",
                     "--pids-limit=32", "--cpus=0.25", "--memory=" + memory,
                     "--memory-swap=" + memory,
                     "--tmpfs", "/workspace:rw,noexec,nosuid,nodev,size=16m,mode=1777",
                     "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=4m,mode=1777"],
              PY_IMAGE, ["python", "-B", "-c", code])
        exit_code = int(command([DOCKER, "wait", name], timeout=20).stdout.strip())
        logs = command([DOCKER, "logs", name]).stdout.strip()
        state = json.loads(command([DOCKER, "inspect", name, "--format", "{{json .State}}"])
                           .stdout)
        return exit_code, logs, state

    try:
        start(prefix + "-pg", ["--network=none", "--memory=256m", "--cpus=1",
                              "-e", "POSTGRES_HOST_AUTH_METHOD=trust"], PG_IMAGE, [])
        for _ in range(60):
            probe = command([DOCKER, "exec", prefix + "-pg", "pg_isready", "-U", "postgres"],
                            check=False)
            process_name = command([DOCKER, "exec", prefix + "-pg", "cat", "/proc/1/comm"], check=False)
            if probe.returncode == 0 and process_name.stdout.strip() == "postgres":
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("isolated PostgreSQL did not become ready")

        sql("""
        CREATE TABLE runs (
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          app_id bigint NOT NULL,
          request_key text NOT NULL UNIQUE,
          request_hash text NOT NULL,
          status text NOT NULL DEFAULT 'queued',
          epoch integer NOT NULL DEFAULT 0,
          lease_until timestamptz,
          UNIQUE (app_id, id)
        );
        CREATE TABLE events (
          run_id bigint REFERENCES runs(id),
          seq integer NOT NULL,
          kind text NOT NULL,
          PRIMARY KEY (run_id, seq)
        );
        INSERT INTO runs(app_id,request_key,request_hash) VALUES (1,'same','digest-a');
        INSERT INTO runs(app_id,request_key,request_hash) VALUES (1,'same','digest-a')
          ON CONFLICT (request_key) DO NOTHING;
        """)
        record("idempotent-insert", sql("SELECT count(*) FROM runs") == "1",
               "two inserts with one key yield one durable run")
        record("payload-conflict-detectable",
               sql("SELECT request_hash <> 'digest-b' FROM runs WHERE request_key='same'") == "t",
               "API must reject key reuse with a changed digest; DB stores original digest")
        sql("INSERT INTO runs(app_id,request_key,request_hash) VALUES (2,'second','digest-c');")
        run_one = sql("SELECT id FROM runs WHERE request_key='same'")
        run_two = sql("SELECT id FROM runs WHERE request_key='second'")
        claim = """
        WITH candidate AS (
          SELECT id FROM runs WHERE status='queued'
            OR (status='running' AND lease_until<clock_timestamp())
          ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE runs r SET status='running',epoch=epoch+1,
          lease_until=clock_timestamp()+interval '30 seconds'
          FROM candidate c WHERE r.id=c.id RETURNING r.id;
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(sql, [claim, claim]))
        record("concurrent-distinct-claims", set(claimed) == {run_one, run_two},
               {"claimed_ids": sorted(claimed)})
        record("busy-run-not-reclaimed", sql(claim) == "", "valid leases are skipped")
        sql("UPDATE runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=" + run_one)
        record("expired-lease-recovered", sql(claim) == run_one and
               sql("SELECT epoch FROM runs WHERE id=" + run_one) == "2", "same run, new fence epoch")
        stale = sql("UPDATE runs SET status='succeeded' WHERE id=" + run_one + " AND epoch=1 "
                    "AND status='running' RETURNING id")
        record("stale-worker-fenced", stale == "", "epoch 1 cannot publish after epoch 2")
        sql("UPDATE runs SET status='cancelled' WHERE id=" + run_one)
        late = sql("UPDATE runs SET status='succeeded' WHERE id=" + run_one + " AND epoch=2 "
                   "AND status='running' RETURNING id")
        record("cancel-blocks-late-success", late == "", "cancelled is terminal")

        sql(f"INSERT INTO events(run_id,seq,kind) VALUES ({run_two},1,'started'),({run_two},2,'text_delta')")
        record("event-replay-cursor", sql("SELECT seq FROM events WHERE run_id=" + run_two + " "
               "AND seq>1 ORDER BY seq") == "2", "cursor returns only unseen event")
        sql(f"INSERT INTO events(run_id,seq,kind) VALUES ({run_two},2,'text_delta') ON CONFLICT DO NOTHING")
        record("event-unique-sequence", sql("SELECT count(*) FROM events WHERE run_id=" + run_two) == "2",
               "duplicate sequence does not duplicate durable events")

        crash_query = f"""
        SET application_name='forge_p0_crash';
        BEGIN;
        UPDATE runs SET status='succeeded' WHERE id={run_two};
        INSERT INTO events(run_id,seq,kind) VALUES ({run_two},3,'succeeded');
        SELECT pg_sleep(15);
        COMMIT;
        """
        process = subprocess.Popen([DOCKER, "exec", "-i", prefix + "-pg", "psql", "-X", "-qAt",
                                    "-v", "ON_ERROR_STOP=1", "-U", "postgres"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        process.stdin.write(crash_query)
        process.stdin.close()
        for _ in range(60):
            pid = sql("SELECT pid FROM pg_stat_activity WHERE application_name='forge_p0_crash' "
                      "AND wait_event='PgSleep'")
            if pid:
                break
            time.sleep(0.1)
        else:
            process.kill()
            process.wait()
            raise RuntimeError("crash probe did not reach transaction checkpoint")
        sql("SELECT pg_terminate_backend(" + pid + ")")
        process.wait(timeout=10)
        record("crash-rolls-back-result-and-event", sql("SELECT status FROM runs WHERE id=" + run_two) == "running"
               and sql("SELECT count(*) FROM events WHERE run_id=" + run_two + " AND seq=3") == "0",
               "terminated backend leaves neither success status nor success event")

        command([DOCKER, "restart", prefix + "-pg"], timeout=30)
        for _ in range(60):
            if command([DOCKER, "exec", prefix + "-pg", "pg_isready", "-U", "postgres"],
                       check=False).returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("restarted PostgreSQL did not become ready")
        record("database-restart-preserves-runs", sql("SELECT count(*) FROM runs") == "2",
               "isolated anonymous volume survives container restart")

        code, logs, _ = sandbox("from pathlib import Path; print(Path('/sys/fs/cgroup/cpu.max').read_text().strip()); "
                                "print(Path('/sys/fs/cgroup/memory.max').read_text().strip())")
        record("cgroup-limits", code == 0 and logs == "25000 100000\n67108864", logs)
        code, logs, _ = sandbox("import errno; from pathlib import Path\n"
                                "try:\n Path('/workspace/fill').write_bytes(b'x'*(20*1024*1024))\n"
                                "except OSError as e:\n print(e.errno); raise SystemExit(0 if e.errno==errno.ENOSPC else 1)\n"
                                "raise SystemExit(1)")
        record("scratch-disk-hard-limit", code == 0 and logs == "28", "16MiB tmpfs rejects 20MiB write with ENOSPC")
        code, _, state = sandbox("blob=bytearray(256*1024*1024); print(len(blob))")
        record("memory-limit-kills-workload", code == 137 and state["OOMKilled"],
               {"exit_code": code, "oom_killed": state["OOMKilled"]})
        code, logs, _ = sandbox("import os,errno\n"
                                "try:\n open('/etc/forge-p0','w').write('sentinel')\n"
                                "except OSError as e:\n print('write-denied'); raise SystemExit(0)\n"
                                "raise SystemExit(1)")
        record("rootfs-write-denied", code == 0 and logs == "write-denied", "unprivileged read-only rootfs")

        name = prefix + "-timeout"
        start(name, ["--network=none", "--read-only", "--cpus=0.25", "--memory=64m"],
              PY_IMAGE, ["python", "-c", "import time; time.sleep(30)"])
        try:
            command([DOCKER, "wait", name], timeout=1)
        except subprocess.TimeoutExpired:
            command([DOCKER, "kill", name])
        state = json.loads(command([DOCKER, "inspect", name, "--format", "{{json .State}}"])
                           .stdout)
        record("controller-timeout-stops-workload", not state["Running"] and state["ExitCode"] == 137,
               "controller kills only its own container after deadline")
    finally:
        cleanup = []
        for name in sorted(owned):
            result = command([DOCKER, "rm", "-f", "-v", name], check=False)
            cleanup.append({"name": name, "removed": result.returncode == 0})
        args.output.write_text(json.dumps({"postgres_image": PG_IMAGE, "python_image": PY_IMAGE,
                                          "checks": records, "cleanup": cleanup}, indent=2) + "\n")
    if not all(r["removed"] for r in cleanup):
        raise RuntimeError("spike cleanup failed; inspect recorded owned names")
    print(json.dumps({"passed": len(records), "all_passed": all(r["passed"] for r in records),
                      "cleanup_ok": all(r["removed"] for r in cleanup)}))


if __name__ == "__main__":
    main()
