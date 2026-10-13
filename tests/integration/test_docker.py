import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
IMAGE = "traceviz:test"
pytestmark = pytest.mark.slow


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kwargs)


@pytest.fixture(scope="module")
def image():
    build = docker("build", "-t", IMAGE, str(ROOT), timeout=1200)
    assert build.returncode == 0, build.stderr[-3000:]
    return IMAGE


def run_args(data: Path) -> list[str]:
    return ["run", "--rm", "--init", "--network", "host", "-v", f"{data}:/data"]


def test_cli_trace_in_container_with_baked_geo(image, tmp_path):
    result = docker(*run_args(tmp_path), image, "trace", "1.1.1.1", "--cycles", "2", "--json", timeout=180)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["destination_reached"] is True and data["hops"][-1]["ip"] == "1.1.1.1"
    assert any(h["geo"] and h["geo"]["status"] == "geo" for h in data["hops"])


def test_server_in_container_serves_ui_and_reports_ready(image, tmp_path):
    name = f"traceviz-test-{os.getpid()}"
    started = docker("run", "-d", "--rm", "--init", "--name", name, "--network", "host",
                     "-v", f"{tmp_path}:/data", image, "serve", "--port", "18080", timeout=60)
    assert started.returncode == 0, started.stderr
    try:
        health = None
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18080/api/health", timeout=2) as r:
                    health = json.load(r)
                break
            except OSError:
                time.sleep(0.5)
        assert health is not None, "server never answered /api/health"
        assert health["probe_ok"] is True and health["geo_available"] is True
        with urllib.request.urlopen("http://127.0.0.1:18080/", timeout=5) as r:
            assert '<div id="root">' in r.read().decode()
    finally:
        assert docker("stop", name, timeout=60).returncode == 0


def test_docker_stop_saves_a_running_monitor(image, tmp_path):
    name = f"traceviz-mon-{os.getpid()}"
    started = docker("run", "-d", "--init", "--name", name, "--network", "host",
                     "-v", f"{tmp_path}:/data", image, "monitor", "1.1.1.1", timeout=60)
    assert started.returncode == 0, started.stderr
    try:
        time.sleep(5)
        assert docker("stop", name, timeout=60).returncode == 0
        assert docker("wait", name, timeout=30).stdout.strip() == "0"
    finally:
        docker("rm", "-f", name, timeout=30)
    history = docker(*run_args(tmp_path), image, "history", "--json", timeout=60)
    assert [r["status"] for r in json.loads(history.stdout)] == ["stopped"]
