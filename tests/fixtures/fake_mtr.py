"""Stand-in for mtr in tests: fake_mtr.py MODE FIXTURE [ignored mtr args...]

MODE: replay | hang | fail | stderr-only
"""

import sys
import time

mode, fixture = sys.argv[1], sys.argv[2]
if mode == "fail":
    print("mtr: Failure to open IPv4 sockets: Permission denied", file=sys.stderr)
    sys.exit(1)
if mode == "stderr-only":
    print("mtr: Failed to resolve host: x: Name or service not known", file=sys.stderr)
    sys.exit(0)
with open(fixture) as f:
    for line in f:
        print(line, end="", flush=True)
if mode == "hang":
    time.sleep(3600)
