"""Opt-in isolated Lima guest: cached image transfer and native bounded ext4 disks."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent
LIMA = "/opt/homebrew/bin/limactl"
DOCKER = "/opt/homebrew/bin/docker"
PG = "sha256:25a89970a83255ae96484d709005bb35aa71f7455f941bc1634514f31c5d5c62"
PY = "sha256:75496575cd8e3aeb3fe561f0384f661d490c14770eda935d2302d61ca20a0b2d"
DISKS = ("fqdb01", "fqart01")
VM = "forge-quota"
CAPACITY = 256 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "p0-linux-quota-results.json")
    args = parser.parse_args()
    if not args.execute:
        print("Preview: dedicated LIMA_HOME, 2CPU/4GiB/12GiB guest, two 256MiB ext4 disks; "
              "fixed Ubuntu download + signed Ubuntu packages + own SSH key; cached PG/Python; "
              "ENOSPC/restart/remount/VM restart; save results outside temporary files; owned cleanup.")
        return
    # Lima's Unix sockets have a host path-length limit; keep exclusively owned
    # runtime/key files in a short private temporary path, evidence stays in ROOT.
    work = Path(tempfile.mkdtemp(prefix="fq-", dir="/private/tmp"))
    env = os.environ.copy()
    env["LIMA_HOME"] = str(work / "lima")
    checks, timings = [], []
    owned_disks = []
    error = None
    cleanup = {"vm": False, "disks": False, "temporary_files": False, "errors": []}
    started = time.monotonic()

    def cmd(argv, *, timeout=90, check=True):
        begin = time.monotonic()
        result = subprocess.run(argv, env=env, capture_output=True, timeout=timeout)
        timings.append({"command": Path(argv[0]).name, "seconds": round(time.monotonic() - begin, 3),
                        "exit_code": result.returncode})
        if check and result.returncode:
            # Never publish Lima cloud-init/SSH diagnostics, which may contain configuration.
            diagnostic = result.stderr.decode(errors="replace").lower()
            reasons = [phrase for phrase in ("too long", "socket", "invalid", "not found",
                       "does not exist", "permission denied", "digest", "additional disk")
                       if phrase in diagnostic]
            raise RuntimeError(f"{Path(argv[0]).name} operation failed, exit {result.returncode}; "
                               f"diagnostic categories: {','.join(reasons) or 'unclassified'}")
        return result

    def lima(*argv, **kwargs):
        return cmd([LIMA, "--tty=false", *argv], **kwargs)

    def guest(*argv, **kwargs):
        return lima("shell", VM, *argv, **kwargs)

    def docker(*argv, **kwargs):
        return guest("sudo", "docker", *argv, **kwargs)

    def record(name, passed, evidence):
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})
        print(f"{name}: {bool(passed)}", flush=True)
        if not passed:
            raise AssertionError(name)

    def filesystem(scope):
        path = "/mnt/lima-" + DISKS[0 if scope == "db" else 1]
        data = json.loads(guest("findmnt", "-J", "-o", "SOURCE,FSTYPE,UUID", "--target", path).stdout)
        fs = data["filesystems"][0]
        capacity = int(guest("python3", "-c", "import os,sys; s=os.statvfs(sys.argv[1]); print(s.f_blocks*s.f_frsize)", path).stdout)
        return {"configured_bytes": CAPACITY, "capacity_bytes": capacity,
                "source": fs["source"], "fstype": fs["fstype"], "uuid": fs["uuid"]}

    def start_pg():
        docker("run", "--pull=never", "-d", "--name", "quota-pg", "--network=none",
               "--cpus=.5", "--memory=256m", "--memory-swap=256m", "--pids-limit=64",
               "--mount", "type=bind,src=/mnt/lima-fqdb01,dst=/bounded",
               "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "PGDATA=/bounded/pgdata", PG)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = json.loads(docker("inspect", "quota-pg", "--format", "{{json .State}}").stdout)
            if not state["Running"]:
                raise RuntimeError("owned PostgreSQL exited before readiness")
            process = docker("exec", "quota-pg", "cat", "/proc/1/comm", check=False)
            ready = docker("exec", "quota-pg", "pg_isready", "-U", "postgres", check=False)
            if process.stdout.strip() == b"postgres" and ready.returncode == 0:
                return
            time.sleep(.5)
        raise RuntimeError("owned PostgreSQL readiness deadline")

    def sql(query):
        return docker("exec", "quota-pg", "psql", "-X", "-qAt", "-U", "postgres", "-v",
                      "ON_ERROR_STOP=1", "-c", query).stdout.decode().strip()

    def stop_pg():
        docker("stop", "--time=20", "quota-pg")
        docker("rm", "-v", "quota-pg")

    def fill(scope):
        disk = DISKS[0 if scope == "db" else 1]
        code = ("import errno,json,os\nwritten=0\ntry:\n"
                " with open('/bounded/fill','wb',buffering=0) as f:\n"
                "  for i in range(512): written+=f.write(b'x'*1048576)\n"
                "  os.fsync(f.fileno())\n"
                "except OSError as e:\n print(json.dumps({'errno':e.errno,'written':written}),flush=True)\n"
                " raise SystemExit(0 if e.errno==errno.ENOSPC else 1)\nraise SystemExit(1)")
        name = "quota-fill-" + scope
        docker("run", "--pull=never", "-d", "--name", name, "--network=none", "--read-only",
               "--cpus=.5", "--memory=128m", "--memory-swap=128m", "--pids-limit=32",
               "--cap-drop=ALL", "--security-opt=no-new-privileges", "--mount",
               f"type=bind,src=/mnt/lima-{disk},dst=/bounded", PY, "python", "-B", "-c", code)
        exit_code = int(docker("wait", name, timeout=180).stdout)
        proof = json.loads(docker("logs", name).stdout)
        docker("rm", name)
        record(scope + "-enospc", exit_code == 0 and proof["errno"] == 28
               and 0 < proof["written"] < CAPACITY, proof)

    try:
        for disk in DISKS:
            owned_disks.append(disk)
            lima("disk", "create", disk, "--size", "256MiB", "--format", "raw")
        print("starting-owned-linux-guest", flush=True)
        lima("start", "--name", VM, "--timeout=20m", str(ROOT / "p0-linux-quota.yaml"), timeout=1260)
        print("owned-linux-guest-ready", flush=True)
        archive = work / "cached-images.tar"
        cmd([DOCKER, "save", "--output", str(archive), PG, PY], timeout=180)
        lima("copy", "--backend=scp", str(archive), VM + ":/tmp/cached-images.tar", timeout=180)
        docker("load", "--input", "/tmp/cached-images.tar", timeout=180)
        guest("rm", "/tmp/cached-images.tar")
        archive.unlink()
        for image_id in (PG, PY):
            assert docker("image", "inspect", image_id, "--format", "{{.Id}}").stdout.decode().strip() == image_id
        db_fs, artifact_fs = filesystem("db"), filesystem("artifact")
        for scope, fs in (("db", db_fs), ("artifact", artifact_fs)):
            record(scope + "-filesystem", fs["fstype"] == "ext4" and fs["uuid"]
                   and CAPACITY // 2 < fs["capacity_bytes"] <= CAPACITY, fs)
        start_pg()
        sql("CREATE TABLE quota_marker(value integer); INSERT INTO quota_marker VALUES(42);")
        stop_pg()
        fill("db")
        # Check independent artifact write while DB remains full.
        guest("sudo", "python3", "-c", "from pathlib import Path; Path('/mnt/lima-fqart01/marker').write_text('scope')")
        record("scope-isolation", db_fs["uuid"] != artifact_fs["uuid"] and
               guest("cat", "/mnt/lima-fqart01/marker").stdout.strip() == b"scope", {"independent_write": True})
        guest("sudo", "rm", "/mnt/lima-fqdb01/fill")
        start_pg()
        record("postgres-restart", sql("SELECT value FROM quota_marker") == "42", {"marker": "42"})
        stop_pg()
        fill("artifact")
        guest("sudo", "rm", "/mnt/lima-fqart01/fill")
        for disk in DISKS:
            target = "/mnt/lima-" + disk
            source = filesystem("db" if disk == DISKS[0] else "artifact")["source"]
            guest("sudo", "umount", target)
            guest("sudo", "mount", source, target)
        start_pg()
        marker, remount_fs = sql("SELECT value FROM quota_marker"), filesystem("db")
        record("guest-remount", marker == "42" and remount_fs["uuid"] == db_fs["uuid"],
               {"marker": marker, "db_uuid": remount_fs["uuid"]})
        stop_pg()
        lima("stop", VM, timeout=180)
        lima("start", VM, "--timeout=10m", timeout=660)
        start_pg()
        marker, restarted_fs = sql("SELECT value FROM quota_marker"), filesystem("db")
        record("vm-restart", marker == "42" and restarted_fs["uuid"] == db_fs["uuid"],
               {"marker": marker, "db_uuid": restarted_fs["uuid"]})
        stop_pg()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}" if not isinstance(exc, subprocess.TimeoutExpired) else "owned operation timeout"
    finally:
        # Stop the guest before disk deletion. No global daemon/context/prune operations.
        try:
            listing = lima("list", "--json").stdout.decode().strip()
            instances = [json.loads(line) for line in listing.splitlines() if line.strip()]
            existing = next((x for x in instances if x.get("name") == VM), None)
            if existing:
                if existing.get("status") != "Stopped":
                    lima("stop", VM, timeout=180)
                listing = lima("list", VM, "--format", "{{.Status}}").stdout.decode().strip()
                if listing != "Stopped":
                    raise RuntimeError("owned VM stop not confirmed")
                lima("delete", VM, timeout=180)
            cleanup["vm"] = True
        except Exception as exc:
            cleanup["errors"].append("VM cleanup: " + type(exc).__name__)
        if cleanup["vm"]:
            try:
                listed = lima("disk", "list", "--json").stdout.decode().strip()
                names = {json.loads(line)["name"] for line in listed.splitlines() if line.strip()}
                for disk in owned_disks:
                    if disk in names:
                        lima("disk", "delete", disk)
                remaining = lima("disk", "list", "--json").stdout.decode().strip()
                assert not any(json.loads(line)["name"] in DISKS for line in remaining.splitlines() if line.strip())
                cleanup["disks"] = True
            except Exception as exc:
                cleanup["errors"].append("disk cleanup: " + type(exc).__name__)
        if cleanup["vm"] and cleanup["disks"] and not cleanup["errors"]:
            try:
                shutil.rmtree(work)  # exclusively mkdtemp-owned; includes only this VM's generated keys
                cleanup["temporary_files"] = True
            except Exception as exc:
                cleanup["errors"].append("temporary cleanup: " + type(exc).__name__)
        args.output.write_text(json.dumps({"checks": checks, "error": error, "cleanup": cleanup,
            "work_path": str(work), "elapsed_seconds": round(time.monotonic() - started, 3),
            "timings": timings, "postgres_image": PG, "python_image": PY}, indent=2) + "\n")
    if error or cleanup["errors"] or not all(cleanup[k] for k in ("vm", "disks", "temporary_files")):
        raise RuntimeError("Linux probe failed; see saved result")


if __name__ == "__main__":
    main()
