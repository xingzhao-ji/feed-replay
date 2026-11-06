"""Run a command with scoped build caches and monitored allocated disk limits."""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

CACHE = Path(os.environ.get("FEED_CACHE", Path.home() / ".cache/job-apps-runtime/feed-replay"))
LIMIT = 200 * 1024**2
FLOOR = 2 * 1024**3


def allocated(path):
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_blocks * 512
        except FileNotFoundError:
            pass
    return total


def check():
    CACHE.mkdir(parents=True, exist_ok=True)
    used, free = allocated(CACHE), shutil.disk_usage(CACHE).free
    if used >= LIMIT or free <= FLOOR:
        raise RuntimeError(f"Storage guard: cache {used} bytes; free {free} bytes")


def main():
    check()
    for folder in ["build", "tmp", "modules", "mpl"]:
        (CACHE / folder).mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(CACHE / "tmp"), CLANG_MODULE_CACHE_PATH=str(CACHE / "modules"), MPLCONFIGDIR=str(CACHE / "mpl"))
    command = sys.argv[1:]
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print(f"cache={allocated(CACHE)} free={shutil.disk_usage(CACHE).free}")
        return
    proc = subprocess.Popen(command, env=env, start_new_session=True)
    try:
        while proc.poll() is None:
            check()
            time.sleep(0.25)
        check()
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        except ProcessLookupError:
            pass
        raise
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
