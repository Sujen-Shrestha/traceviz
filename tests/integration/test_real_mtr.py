import json
import os
import subprocess
import sys

import pytest


@pytest.mark.slow
def test_real_trace_to_cloudflare(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "traceviz", "trace", "1.1.1.1", "--cycles", "2", "--json"],
        env={**os.environ, "TRACEVIZ_DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "completed"
    assert data["destination_reached"] is True
    assert data["hops"][-1]["ip"] == "1.1.1.1"
