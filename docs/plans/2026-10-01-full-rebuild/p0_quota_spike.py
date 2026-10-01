"""Opt-in macOS fixed-size filesystem probe; only owns UUID paths/containers."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import time
import uuid

DOCKER = "/opt/homebrew/bin/docker"
HDI = "/usr/bin/hdiutil"
PG = "sha256:25a89970a83255ae96484d709005bb35aa71f7455f941bc1634514f31c5d5c62"
PY = "sha256:75496575cd8e3aeb3fe561f0384f661d490c14770eda935d2302d61ca20a0b2d"


def cmd(argv, timeout=60, check=True):
    result = subprocess.run(argv, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"{argv[0]} failed with code {result.returncode}: {result.stderr.decode().strip()}")
    return result


def cleanup_probe(owned, mount, image, work, attached):
    result = {"containers": False, "detached": False, "temporary_files": False, "errors": []}
    removed = []
    for name in owned:
        try:
            removed.append(cmd([DOCKER, "rm", "-f", "-v", name], check=False).returncode == 0)
        except Exception as exc:
            removed.append(False)
            result["errors"].append(str(exc))
    result["containers"] = all(removed)
    if attached:
        try:
            cmd([HDI, "detach", str(mount)])
        except Exception as exc:
            result["errors"].append(str(exc))
    try:
        info = plistlib.loads(cmd([HDI, "info", "-plist"]).stdout)
        still_attached = any(x.get("image-path") == str(image) or
                             any(e.get("mount-point") == str(mount) for e in x.get("system-entities", []))
                             for x in info["images"])
        result["detached"] = not still_attached
    except Exception as exc:
        result["errors"].append(str(exc))
    # Unknown attachment state, surviving containers or cleanup error preserve the files.
    if result["containers"] and result["detached"] and not result["errors"]:
        try:
            if image.exists():
                image.unlink()
            mount.rmdir()
            work.rmdir()
            result["temporary_files"] = True
        except Exception as exc:
            result["errors"].append(str(exc))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.execute:
        print("Preview: temporary 256MiB HFSX disk image under this attachment; attach without Finder; "
              "bind only its mount into isolated cached-image containers; PG persistence + ENOSPC; "
              "remove owned containers, detach, then remove owned image. No system settings or downloads.")
        return
    root = Path(__file__).resolve().parent
    work = Path(tempfile.mkdtemp(prefix="quota-probe-", dir=root))
    image, mount = work / "bounded.dmg", work / "mount"
    mount.mkdir()
    prefix = "forge-quota-" + uuid.uuid4().hex[:12]
    owned, checks = [], []
    attached = False
    cleanup = {"containers": False, "detached": False, "temporary_files": False}
    error = None

    def record(name, passed, evidence):
        checks.append({"name": name, "passed": bool(passed), "evidence": evidence})
        print(name + ": " + str(bool(passed)), flush=True)
        if not passed:
            raise AssertionError(name)

    def start(name, image_id, flags, argv, *, bounded=True):
        owned.append(name)
        return cmd([DOCKER, "run", "--pull=never", "-d", "--name", name,
                    "--label", "forge.scope=p0-quota", "--network=none", "--cpus=1",
                    "--memory=256m", "--memory-swap=256m", "--pids-limit=64",
                    *(["--mount", f"type=bind,src={mount},dst=/bounded"] if bounded else []),
                    *flags, image_id, *argv])

    def ready(name=None):
        name = name or prefix + "-pg"
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            state = json.loads(cmd([DOCKER, "inspect", name, "--format", "{{json .State}}"])
                               .stdout)
            if not state["Running"]:
                raise RuntimeError("quota PostgreSQL exited before readiness")
            process = cmd([DOCKER, "exec", name, "cat", "/proc/1/comm"], check=False)
            probe = cmd([DOCKER, "exec", name, "pg_isready", "-U", "postgres"], check=False)
            if process.stdout.strip() == b"postgres" and probe.returncode == 0:
                return
            time.sleep(0.25)
        raise RuntimeError("quota PostgreSQL not ready")

    def sql(query):
        return cmd([DOCKER, "exec", prefix + "-pg", "psql", "-X", "-qAt", "-U", "postgres",
                    "-v", "ON_ERROR_STOP=1", "-c", query]).stdout.decode().strip()

    try:
        cmd([HDI, "create", "-size", "256m", "-fs", "Case-sensitive Journaled HFS+",
             "-volname", prefix, "-type", "UDIF", "-nospotlight", str(image)])
        attached = True  # attempt may attach before a command timeout
        attach = cmd([HDI, "attach", "-nobrowse", "-noautoopen", "-mountpoint", str(mount),
                      "-plist", str(image)])
        info = plistlib.loads(attach.stdout)
        record("fixed-filesystem-mounted", any(x.get("mount-point") == str(mount)
               for x in info["system-entities"]), "256MiB case-sensitive journaled HFS+ image")
        # Bootstrap fresh, credential-free test data on native storage, then copy only
        # after clean stop. No model/app data is seeded, and fsync remains enabled.
        start(prefix + "-seed", PG, ["-e", "POSTGRES_HOST_AUTH_METHOD=trust"], [], bounded=False)
        ready(prefix + "-seed")
        cmd([DOCKER, "stop", "--time=20", prefix + "-seed"])
        (mount / "pgdata").mkdir()
        cmd([DOCKER, "cp", prefix + "-seed:/var/lib/postgresql/data/.", str(mount / "pgdata")], timeout=300)
        print("native-seed-copied-after-clean-stop", flush=True)
        start(prefix + "-pg", PG, ["-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                                   "-e", "PGDATA=/bounded/pgdata"], [])
        ready()
        sql("CREATE TABLE quota_marker(value integer); INSERT INTO quota_marker VALUES(42);")
        cmd([DOCKER, "stop", "--time=20", prefix + "-pg"])
        code = ("import os,errno,json\n"
                "p='/bounded/fill'; written=0\n"
                "try:\n"
                " with open(p,'wb',buffering=0) as f:\n"
                "  for i in range(512):\n"
                "   written+=f.write(b'x'*1048576)\n"
                "  os.fsync(f.fileno())\n"
                "except OSError as e:\n"
                " print(json.dumps({'errno':e.errno,'written':written}),flush=True)\n"
                " raise SystemExit(0 if e.errno==errno.ENOSPC else 1)\n"
                "raise SystemExit(1)")
        start(prefix + "-fill", PY, ["--read-only", "--cap-drop=ALL", "--security-opt",
                                      "no-new-privileges"], ["python", "-B", "-c", code])
        exit_code = int(cmd([DOCKER, "wait", prefix + "-fill"], timeout=300).stdout)
        evidence = json.loads(cmd([DOCKER, "logs", prefix + "-fill"]).stdout)
        record("docker-write-hard-limit", exit_code == 0 and evidence["errno"] == 28
               and evidence["written"] < 256 * 1024 * 1024, evidence)
        (mount / "fill").unlink()
        cmd([DOCKER, "start", prefix + "-pg"])
        ready()
        record("postgres-restart-after-full", sql("SELECT value FROM quota_marker") == "42",
               "cleanly stopped DB survives filesystem fill/free/restart")
        cmd([DOCKER, "stop", "--time=20", prefix + "-pg"])
        cmd([HDI, "detach", str(mount)])
        attached = False
        attached = True
        cmd([HDI, "attach", "-nobrowse", "-noautoopen", "-mountpoint", str(mount), str(image)])
        cmd([DOCKER, "start", prefix + "-pg"])
        ready()
        record("postgres-image-remount-persistence", sql("SELECT value FROM quota_marker") == "42",
               "disk image detached/remounted; DB row retained")
    except Exception as exc:
        error = str(exc)
    finally:
        cleanup = cleanup_probe(owned, mount, image, work, attached)
        args.output.write_text(json.dumps({"checks": checks, "cleanup": cleanup, "error": error,
                                          "seed_strategy": "native-volume-clean-stop-copy",
                                          "postgres_image": PG, "python_image": PY}, indent=2) + "\n")
    if error or cleanup["errors"] or not all(cleanup[x] for x in ("containers", "detached", "temporary_files")):
        raise RuntimeError(error or "quota probe cleanup incomplete; see results")


if __name__ == "__main__":
    main()
