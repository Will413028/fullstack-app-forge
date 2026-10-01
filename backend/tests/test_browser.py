import asyncio
import os
import shutil
import signal
import socket
import subprocess
from pathlib import Path

import httpx
import pytest
from test_run_store import database as database

pytestmark = pytest.mark.asyncio(loop_scope="module")
ROOT = Path(__file__).resolve().parents[2]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def wait_ready(url, expected, process):
    deadline = asyncio.get_running_loop().time() + 90
    async with httpx.AsyncClient(timeout=3) as client:
        while asyncio.get_running_loop().time() < deadline:
            if process.poll() is not None:
                raise AssertionError("owned server exited before readiness")
            try:
                if (await client.get(url)).status_code == expected:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
    raise AssertionError("owned server readiness deadline")


async def test_browser_platform_round_trip(database):
    _, settings = database
    node = shutil.which("node")
    assert node, "Node.js required for real browser test"
    assert (ROOT / "web/.next/standalone/web/server.js").is_file(), "Build web before browser test"
    api_port, web_port = free_port(), free_port()
    origin = f"http://127.0.0.1:{web_port}"
    api_url = f"http://127.0.0.1:{api_port}"
    env = {**os.environ, "FORGE_DATABASE_URL": settings.database_url, "FORGE_PLATFORM_ORIGIN": origin}
    processes = []
    browser = None
    try:
        api = subprocess.Popen(
            [
                str(ROOT / "backend/.venv/bin/uvicorn"),
                "forge.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(api_port),
            ],
            cwd=ROOT / "backend",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        processes.append(api)
        await wait_ready(api_url + "/openapi.json", 200, api)
        web = subprocess.Popen(
            [node, str(ROOT / "web/start.mjs"), "--port", str(web_port)],
            cwd=ROOT,
            env={**env, "FORGE_API_URL": api_url},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        processes.append(web)
        await wait_ready(origin + "/v1/auth/session", 401, web)
        browser = await asyncio.create_subprocess_exec(
            node,
            str(ROOT / "docs/plans/2026-10-01-full-rebuild/p1a_browser_flow.mjs"),
            cwd=ROOT,
            env={**env, "FORGE_TEST_ORIGIN": origin},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = await asyncio.wait_for(browser.communicate(), timeout=300)
        assert browser.returncode == 0, stderr.decode(errors="replace")[-4000:]
        assert b'"scope":"platform browser/API/DB only' in stdout
    finally:
        if browser:
            try:
                os.killpg(browser.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if browser.returncode is None:
                try:
                    await asyncio.wait_for(browser.wait(), timeout=20)
                except TimeoutError:
                    os.killpg(browser.pid, signal.SIGKILL)
                    await browser.wait()
        for process in reversed(processes):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.to_thread(process.wait, timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                await asyncio.to_thread(process.wait, timeout=10)
