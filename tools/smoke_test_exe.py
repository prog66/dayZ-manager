"""Smoke test minimal de l'executable Windows compile."""

from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path


def run_smoke_test(executable: Path, seconds: float = 3.0) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    f"L'executable s'est arrete trop tot (code {process.returncode})."
                )
            time.sleep(0.2)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--seconds", type=float, default=3.0)
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        parser.error(f"Executable introuvable : {executable}")
    run_smoke_test(executable, max(0.5, args.seconds))
    print(f"PACKAGED_SMOKE_OK {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
