import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_sigterm_stops_monitor_saves_and_kills_mtr(tmp_path):
    capture = tmp_path / "capture.txt"  # unique path so we can find our fake mtr afterwards
    shutil.copy(FIXTURES / "mtr_raw_cloudflare.txt", capture)
    env = {
        **os.environ,
        "TRACEVIZ_DATA_DIR": str(tmp_path),
        "TRACEVIZ_GEO_DIR": str(tmp_path / "nogeo"),
        "TRACEVIZ_MTR": f"{sys.executable} {FIXTURES / 'fake_mtr.py'} hang {capture}",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "traceviz", "monitor", "1.1.1.1"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    time.sleep(2)
    proc.send_signal(signal.SIGTERM)
    _, stderr = proc.communicate(timeout=15)
    assert proc.returncode == 0, stderr
    assert "Monitor stopped; results saved." in stderr
    history = subprocess.run([sys.executable, "-m", "traceviz", "history", "--json"],
                             env=env, capture_output=True, text=True, check=True)
    assert [r["status"] for r in json.loads(history.stdout)] == ["stopped"]
    assert subprocess.run(["pgrep", "-f", str(capture)]).returncode == 1  # fake mtr is gone


def _fake_mtr_env(tmp_path):
    capture = tmp_path / "capture.txt"
    shutil.copy(FIXTURES / "mtr_raw_cloudflare.txt", capture)
    return capture, {
        **os.environ,
        "TRACEVIZ_DATA_DIR": str(tmp_path),
        "TRACEVIZ_GEO_DIR": str(tmp_path / "nogeo"),
        "TRACEVIZ_MTR": f"{sys.executable} {FIXTURES / 'fake_mtr.py'} hang {capture}",
    }


def _statuses(env):
    history = subprocess.run([sys.executable, "-m", "traceviz", "history", "--json"],
                             env=env, capture_output=True, text=True, check=True)
    return [r["status"] for r in json.loads(history.stdout)]


def test_sigterm_stops_trace_with_exit_143(tmp_path):
    _, env = _fake_mtr_env(tmp_path)
    proc = subprocess.Popen([sys.executable, "-m", "traceviz", "trace", "1.1.1.1"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2)
    proc.send_signal(signal.SIGTERM)
    _, stderr = proc.communicate(timeout=15)
    assert proc.returncode == 143, stderr
    assert "Trace stopped; partial results saved." in stderr
    assert _statuses(env) == ["stopped"]


def test_repeated_signals_still_save_the_session(tmp_path):
    capture, env = _fake_mtr_env(tmp_path)
    proc = subprocess.Popen([sys.executable, "-m", "traceviz", "monitor", "1.1.1.1"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(2)
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGTERM):  # closed terminal, then docker stop
        proc.send_signal(sig)
        time.sleep(0.005)
    _, stderr = proc.communicate(timeout=15)
    assert proc.returncode == 0, stderr
    assert _statuses(env) == ["stopped"]
    assert subprocess.run(["pgrep", "-f", str(capture)]).returncode == 1
