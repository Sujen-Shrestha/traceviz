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
