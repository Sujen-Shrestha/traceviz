"""Stand-in for mtr in tests: fake_mtr.py MODE FIXTURE [ignored mtr args...]

MODE: replay | hang | fail | stderr-only | silent | noisy | pgid (FIXTURE = file to write our process group id to)
"""

import sys
import time

mode, fixture = sys.argv[1], sys.argv[2]
if mode == "fail":
    print("mtr: Failure to open IPv4 sockets: Permission denied", file=sys.stderr)
    sys.exit(1)
if mode == "pgid":
    import os

    with open(fixture, "w") as out:
        out.write(str(os.getpgid(0)))
    sys.exit(0)
if mode == "silent":
    sys.exit(0)
if mode == "noisy":
    # More stderr than a pipe buffer holds, before any stdout.
    sys.stderr.write("mtr: warning: something odd\n" * 20000)
    sys.stderr.flush()
if mode == "stderr-only":
    print("mtr: Failed to resolve host: x: Name or service not known", file=sys.stderr)
    sys.exit(0)
with open(fixture) as f:
    for line in f:
        print(line, end="", flush=True)
if mode == "hang":
    time.sleep(3600)
