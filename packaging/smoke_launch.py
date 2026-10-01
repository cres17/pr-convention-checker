"""Legacy process-liveness probe; use verify_package.py for real verification.

An error dialog can pass this probe. It does not prove UI or analysis readiness.

Exit code 1 (with the app's output) if it dies early, which catches missing
libraries, broken bundles and import errors that unit tests cannot see. It runs
Qt headless (offscreen) so it works on CI runners without a display.

    python packaging/smoke_launch.py dist/DriftGate.app/Contents/MacOS/DriftGate
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time


def main(executable: str, seconds: float = 12.0) -> int:
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu",
    }
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([executable], stdout=log, stderr=subprocess.STDOUT, env=env)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            code = process.poll()
            if code is not None:
                log.seek(0)
                print(log.read().decode("utf-8", errors="replace")[-4000:])
                print(f"FAILED: {executable} exited with code {code} after starting")
                return 1
            time.sleep(0.5)
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
    print(f"OK: {executable} was still running after {seconds:.0f}s")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
