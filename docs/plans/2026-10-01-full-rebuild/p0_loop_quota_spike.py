"""Owned local-driver ext4 loop primitive; never changes Docker daemon settings."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
PG = "postgres@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24"
PY = "sha256:75496575cd8e3aeb3fe561f0384f661d490c14770eda935d2302d61ca20a0b2d"
CAPACITY = 256 * 1024 * 1024


class DiagnosticComplete(Exception):
    """End the diagnostic branch before PostgreSQL and quota acceptance."""


def require_settled(uncertain):
    if uncertain:
        raise RuntimeError("daemon mutation outcome unknown; retain owned resources for reconciliation")


def check_backing_identity(file_device, mount_device, mount_number, inode, size, device, loop):
    if (file_device != mount_device or loop["back-maj:min"] != mount_number
            or loop["name"] != device or int(loop["back-ino"]) != inode
            or int(loop["sizelimit"]) != 0 or size != CAPACITY):
        raise RuntimeError("owned loop backing identity mismatch")
    return {"device": device, "backing_device": mount_number, "file_device": file_device,
            "inode": inode, "image_bytes": size}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--tools-image", default="forge-quota-tools:p0")
    parser.add_argument("--diagnose-io", action="store_true")
    parser.add_argument("--diagnose-fill", action="store_true")
    parser.add_argument("--io-mib", type=int, choices=(16, 128), default=16)
    parser.add_argument("--writer-memory-mib", type=int, choices=(128, 512), default=128)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        args.output = ROOT / ("p0-loop-artifact-fill-diagnostic.json" if args.diagnose_fill else
                             f"p0-loop-io-{args.io_mib}m-diagnostic.json" if args.diagnose_io else
                             "p0-loop-quota-results.json")
    if args.diagnose_io and args.diagnose_fill:
        parser.error("choose one diagnostic branch")
    if not args.execute:
        print("Preview: two owned 256MiB ext4 images, SYS_ADMIN/MKNOD loop controller, "
              "Docker local mount driver, unprivileged PG/writers, ENOSPC/remount/remap, owned cleanup")
        return
    prefix = "forge-loop-" + uuid4().hex[:12]
    backing = prefix + "-images"
    controller = prefix + "-controller"
    containers, drivers, loops, pending = [], {}, {}, set()
    checks, timings, diagnostics, uncertain, limits = [], [], [], [], []
    error = None
    cleanup = {"containers": False, "volumes": False, "loop_devices": False,
               "backing_volume": False, "errors": []}

    def cmd(*arguments, check=True, timeout=90, read_only=False):
        begin = time.monotonic()
        try:
            result = subprocess.run(["docker", *arguments], capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            timings.append({"operation": arguments[0], "seconds": round(time.monotonic() - begin, 3),
                            "exit_code": None, "deadline_seconds": timeout})
            if not read_only:
                uncertain.append({"operation": arguments[0], "reason": "timeout"})
            raise
        timings.append({"operation": arguments[0], "seconds": round(time.monotonic() - begin, 3),
                        "exit_code": result.returncode})
        known_absent = ((arguments[0] == "rm" and b"No such container" in result.stderr)
                        or (arguments[:2] == ("volume", "rm") and b"no such volume" in result.stderr.lower()))
        if result.returncode and not read_only and not known_absent:
            uncertain.append({"operation": arguments[0], "reason": "nonzero"})
        if check and result.returncode:
            raise RuntimeError("owned docker operation failed: " + result.stderr.decode(errors="replace")[-1000:])
        return result

    def ctl(*arguments, **kwargs):
        return cmd("exec", controller, *arguments, **kwargs)

    def label_flags():
        return ["--label", "forge.spike=loop-quota", "--label", "forge.spike-id=" + prefix]

    def remove_container(name):
        result = cmd("rm", "-f", "-v", name, check=False)
        if result.returncode and b"No such container" not in result.stderr:
            raise RuntimeError("owned container cleanup incomplete")

    def remove_volume(name):
        result = cmd("volume", "rm", name, check=False)
        if result.returncode and b"no such volume" not in result.stderr.lower():
            raise RuntimeError("owned volume cleanup incomplete")

    def start_controller():
        containers.append(controller)
        rules = [flag for minor in range(32) for flag in ("--device-cgroup-rule", f"b 7:{minor} rwm")]
        cmd("run", "--pull=never", "-d", "--name", controller, *label_flags(), "--network=none",
            "--read-only", "--memory=128m", "--memory-swap=128m", "--cpus=.5", "--pids-limit=64",
            "--tmpfs", "/tmp:size=16m", "--cap-drop=ALL", "--cap-add=SYS_ADMIN", "--cap-add=MKNOD",
            "--security-opt=no-new-privileges", "--device=/dev/loop-control:/dev/loop-control:rwm", *rules,
            "--mount", f"type=volume,src={backing},dst=/images,volume-nocopy", args.tools_image,
            "sleep", "1800")
        ctl("sh", "-c", 'n=0; while [ "$n" -lt 32 ]; do '
            'test -b "/dev/loop$n" || mknod "/dev/loop$n" b 7 "$n"; n=$((n+1)); done')

    def identity(scope, device):
        if not re.fullmatch(r"/dev/loop(?:[0-9]|[12][0-9]|3[01])", device):
            raise RuntimeError("loop device outside allowlist")
        stats = ctl("stat", "-c", "%d:%i:%s", f"/images/{scope}.raw", "/images", read_only=True).stdout.decode().splitlines()
        file_device, inode, size = map(int, stats[0].split(":"))
        mount_device = int(stats[1].split(":")[0])
        mountinfo = ctl("cat", "/proc/self/mountinfo", read_only=True).stdout.decode().splitlines()
        mounts = [line.split()[2] for line in mountinfo if line.split()[4] == "/images"]
        if len(mounts) != 1:
            raise RuntimeError("owned backing mount identity ambiguous")
        data = json.loads(ctl("losetup", "--json", "--output", "NAME,BACK-INO,BACK-MAJ:MIN,SIZELIMIT", device, read_only=True).stdout)
        devices = data["loopdevices"]
        if len(devices) != 1:
            raise RuntimeError("owned loop backing identity mismatch")
        return check_backing_identity(file_device, mount_device, mounts[0], inode, size, device, devices[0])

    def attach(scope):
        pending.add(scope)
        device = ctl("losetup", "--find", "--show", "--nooverlap", f"/images/{scope}.raw").stdout.decode().strip()
        loops[scope] = identity(scope, device)
        pending.remove(scope)

    def detach(scope):
        item = loops[scope]
        if identity(scope, item["device"]) != item:
            raise RuntimeError("owned loop attachment identity changed; refuse detach")
        ctl("losetup", "--detach", item["device"])
        # Linux detach can be deferred while references remain. Require actual unbinding.
        ctl("test", "!", "-e", f"/sys/block/{Path(item['device']).name}/loop/backing_file", read_only=True)
        del loops[scope]

    def mount_driver(scope):
        name = prefix + "-" + scope
        drivers[scope] = name
        cmd("volume", "create", *label_flags(), "--driver", "local", "--opt", "type=ext4",
            "--opt", "device=" + loops[scope]["device"], "--opt", "o=rw", name)
        options = json.loads(cmd("volume", "inspect", name, "--format", "{{json .Options}}", read_only=True).stdout)
        assert options == {"type": "ext4", "device": loops[scope]["device"], "o": "rw"}

    def python(scope, code, suffix, timeout=120):
        name = prefix + "-" + suffix
        containers.append(name)
        cmd("run", "--pull=never", "-d", "--name", name, *label_flags(), "--network=none", "--read-only",
            f"--memory={args.writer_memory_mib}m", f"--memory-swap={args.writer_memory_mib}m",
            "--cpus=.5", "--pids-limit=32", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--mount", f"type=volume,src={drivers[scope]},dst=/bounded,volume-nocopy",
            PY, "python", "-B", "-c", code)
        actual = json.loads(cmd("inspect", name, "--format",
            '{"memory":{{.HostConfig.Memory}},"memory_swap":{{.HostConfig.MemorySwap}},'
            '"nano_cpus":{{.HostConfig.NanoCpus}},"pids":{{.HostConfig.PidsLimit}},'
            '"readonly":{{.HostConfig.ReadonlyRootfs}},"privileged":{{.HostConfig.Privileged}},'
            '"network":{{json .HostConfig.NetworkMode}},"cap_drop":{{json .HostConfig.CapDrop}}}',
            read_only=True).stdout)
        expected = {"memory": args.writer_memory_mib * 1048576, "memory_swap": args.writer_memory_mib * 1048576,
                    "nano_cpus": 500000000, "pids": 32, "readonly": True, "privileged": False,
                    "network": "none", "cap_drop": ["ALL"]}
        limits.append({"container": name, "actual": actual, "expected": expected})
        if actual != expected:
            raise RuntimeError("owned writer limits readback mismatch")
        try:
            status = int(cmd("wait", name, timeout=timeout, read_only=True).stdout)
        except subprocess.TimeoutExpired:
            state = cmd("inspect", name, "--format", "{{json .State}}", check=False, read_only=True)
            logs = cmd("logs", "--tail", "20", name, check=False, read_only=True)
            diagnostics.append({"container": name, "state": state.stdout.decode(errors="replace"),
                                "log": (logs.stdout + logs.stderr).decode(errors="replace")})
            raise
        logs = cmd("logs", name, read_only=True)
        output = logs.stdout
        if logs.stderr:
            diagnostics.append({"container": name, "progress": logs.stderr.decode(errors="replace")})
        if status != 0:
            state = cmd("inspect", name, "--format", "{{json .State}}", read_only=True)
            diagnostics.append({"container": name, "exit_code": status,
                                "state": state.stdout.decode(errors="replace"),
                                "stdout": output.decode(errors="replace"),
                                "stderr": logs.stderr.decode(errors="replace")})
        remove_container(name)
        assert status == 0, f"owned writer/reader failed with exit {status}"
        return json.loads(output)

    def filesystem(scope):
        proof = python(scope, "import json,os\ns=os.statvfs('/bounded')\n"
                       "row=next(x.split() for x in open('/proc/self/mountinfo') if x.split()[4]=='/bounded')\n"
                       "i=row.index('-')\nprint(json.dumps({'capacity_bytes':s.f_blocks*s.f_frsize,"
                       "'fstype':row[i+1],'source':row[i+2],'device_number':row[2]}))", scope + "-fs")
        proof["configured_bytes"] = CAPACITY
        proof["uuid"] = ctl("blkid", "-s", "UUID", "-o", "value", f"/images/{scope}.raw", read_only=True).stdout.decode().strip()
        return proof

    def record(name, passed, proof):
        checks.append({"name": name, "passed": bool(passed), "evidence": proof})
        print(f"{name}: {bool(passed)}", flush=True)
        assert passed, name

    pg_name = prefix + "-pg"

    def start_pg():
        containers.append(pg_name)
        cmd("run", "--pull=never", "-d", "--name", pg_name, *label_flags(), "--network=none",
            "--cpus=.5", "--memory=256m", "--memory-swap=256m", "--pids-limit=64",
            "--mount", f"type=volume,src={drivers['db']},dst=/bounded,volume-nocopy",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "PGDATA=/bounded/pgdata", PG)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            ready = cmd("exec", pg_name, "sh", "-c",
                        '[ "$(cat /proc/1/comm)" = postgres ] && pg_isready -U postgres', check=False, read_only=True)
            if ready.returncode == 0:
                return
            time.sleep(.5)
        raise RuntimeError("owned PostgreSQL readiness deadline")

    def sql(query):
        return cmd("exec", pg_name, "psql", "-X", "-qAt", "-U", "postgres", "-v", "ON_ERROR_STOP=1",
                   "-c", query, read_only=query.lstrip().upper().startswith("SELECT ")).stdout.decode().strip()

    def stop_pg():
        cmd("stop", "--time=20", pg_name)
        remove_container(pg_name)

    def fill(scope):
        proof = python(scope, "import errno,json,os,sys,time\nfrom pathlib import Path\n"
                       "n=0;t=time.monotonic()\ntry:\n"
                       " with open('/bounded/fill','wb',buffering=0) as f:\n"
                       "  for i in range(512):\n"
                       "   n+=f.write(b'x'*1048576)\n"
                       "   if (i+1)%16==0:\n"
                       "    print(json.dumps({'written':n,'elapsed_seconds':time.monotonic()-t,"
                       "'memory_events':Path('/sys/fs/cgroup/memory.events').read_text()}),file=sys.stderr,flush=True)\n"
                       "  os.fsync(f.fileno())\nexcept OSError as e:\n"
                       " print(json.dumps({'errno':e.errno,'written':n,'elapsed_seconds':time.monotonic()-t}),flush=True)\n"
                       " raise SystemExit(0 if e.errno==errno.ENOSPC else 1)\nraise SystemExit(1)", scope + "-fill")
        record(scope + "-enospc", proof["errno"] == 28 and 0 < proof["written"] < CAPACITY, proof)

    try:
        image_id = cmd("image", "inspect", args.tools_image, "--format", "{{.Id}}", read_only=True).stdout.decode().strip()
        cmd("volume", "create", *label_flags(), backing)
        start_controller()
        versions = ctl("apk", "info", "-v", "e2fsprogs", "util-linux", read_only=True).stdout.decode().strip()
        print("owned-loop-controller-ready", flush=True)
        for scope in ("db", "artifact"):
            ctl("truncate", "-s", str(CAPACITY), f"/images/{scope}.raw")
            ctl("mkfs.ext4", "-F", "-q", f"/images/{scope}.raw")
            attach(scope)
            mount_driver(scope)
        db_fs, artifact_fs = filesystem("db"), filesystem("artifact")
        for scope, proof in (("db", db_fs), ("artifact", artifact_fs)):
            record(scope + "-filesystem", proof["fstype"] == "ext4" and proof["uuid"]
                   and proof["source"] == loops[scope]["device"]
                   and CAPACITY // 2 < proof["capacity_bytes"] <= CAPACITY, proof)
        if args.diagnose_io:
            proof = python("db", "import json,os,time,sys\nfrom pathlib import Path\n"
                           "t=time.monotonic(); samples=[]; n=0\n"
                           "with open('/bounded/io-probe','wb',buffering=0) as f:\n"
                           f" for i in range({args.io_mib}):\n"
                           "  n+=f.write(b'x'*1048576); samples.append(time.monotonic()-t)\n"
                           "  if (i+1)%16==0:\n"
                           "   print(json.dumps({'written':n,'elapsed_seconds':time.monotonic()-t,"
                           "'memory_events':Path('/sys/fs/cgroup/memory.events').read_text()}),file=sys.stderr,flush=True)\n"
                           " before=time.monotonic();os.fsync(f.fileno());synced=time.monotonic()-before\n"
                           "print(json.dumps({'written':n,'write_samples_seconds':samples,"
                           "'fsync_seconds':synced,'total_seconds':time.monotonic()-t}),flush=True)", "io-diagnostic")
            record("db-io-diagnostic", proof["written"] == args.io_mib * 1024 * 1024, proof)
            raise DiagnosticComplete
        if args.diagnose_fill:
            fill("artifact")
            raise DiagnosticComplete
        start_pg()
        sql("CREATE TABLE quota_marker(value integer); INSERT INTO quota_marker VALUES(42);")
        stop_pg()
        fill("db")
        independent = python("artifact", "import json\nfrom pathlib import Path\n"
                             "p=Path('/bounded/marker');p.write_text('scope');print(json.dumps({'marker':p.read_text()}))",
                             "isolation")
        record("scope-isolation", db_fs["uuid"] != artifact_fs["uuid"] and independent["marker"] == "scope",
               {"independent_write": True})
        python("db", "import os,json;os.unlink('/bounded/fill');print(json.dumps({'removed':True}))", "db-release")
        start_pg()
        marker = sql("SELECT value FROM quota_marker")
        record("postgres-restart", marker == "42", {"marker": marker})
        stop_pg()
        fill("artifact")
        python("artifact", "import os,json;os.unlink('/bounded/fill');print(json.dumps({'removed':True}))", "art-release")
        for name in drivers.values():
            remove_volume(name)
        drivers.clear()
        for scope in ("db", "artifact"):
            mount_driver(scope)
        start_pg()
        marker = sql("SELECT value FROM quota_marker")
        record("volume-remount", marker == "42", {"marker": marker, "db_uuid": filesystem("db")["uuid"]})
        stop_pg()
        for name in drivers.values():
            remove_volume(name)
        drivers.clear()
        for scope in ("db", "artifact"):
            detach(scope)
        remove_container(controller)
        start_controller()
        for scope in ("db", "artifact"):
            attach(scope)
            mount_driver(scope)
        start_pg()
        marker = sql("SELECT value FROM quota_marker")
        record("controller-remap", marker == "42", {"marker": marker, "db_uuid": filesystem("db")["uuid"]})
        stop_pg()
    except DiagnosticComplete:
        pass
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            require_settled(uncertain)
            for name in dict.fromkeys(containers):
                if name != controller:
                    remove_container(name)
            cleanup["containers"] = True
            for name in drivers.values():
                remove_volume(name)
            cleanup["volumes"] = True
            for scope in pending:
                found = ctl("losetup", "-j", f"/images/{scope}.raw", read_only=True).stdout.decode().strip()
                if found:
                    device = found.split(":", 1)[0]
                    loops[scope] = identity(scope, device)
            for scope in list(loops):
                detach(scope)
            cleanup["loop_devices"] = True
            remove_container(controller)
            require_settled(uncertain)
            remove_volume(backing)
            cleanup["backing_volume"] = True
        except Exception as exc:
            cleanup["errors"].append(f"{type(exc).__name__}: {exc}")
        result = {"checks": checks, "error": error, "cleanup": cleanup, "prefix": prefix,
                  "backing_volume": backing, "controller": controller, "remaining_loops": loops,
                  "pending_attach": sorted(pending), "uncertain_mutations": uncertain,
                  "timings": timings, "diagnostics": diagnostics, "writer_limits": limits,
                  "writer_memory_mib": args.writer_memory_mib,
                  "scope": ("isolated artifact fill diagnostic only; not lifecycle acceptance" if args.diagnose_fill else
                            f"{args.io_mib}MiB I/O diagnostic only; not quota acceptance" if args.diagnose_io else
                            "local volume lifecycle and controller remap; not Docker daemon/host reboot")}
        if "image_id" in locals():
            result["tools_image_id"] = image_id
        if "versions" in locals():
            result["tools_versions"] = versions
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": len(checks), "error": error, "cleanup": cleanup}), flush=True)
    if error or cleanup["errors"] or not all(cleanup[k] for k in ("containers", "volumes", "loop_devices", "backing_volume")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
