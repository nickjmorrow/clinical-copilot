"""Development only: run the worker, and restart it when `app/` changes *or when it dies*.

Run with `python -m app.worker.dev`; `docker-compose.yml` does.

`watchfiles` on its own restarts on a change and on nothing else. A worker that
died between edits — killed from outside, with no traceback and no "worker
stopped" — stayed dead while its container still reported "running", because
the container's process was the file watcher and not the worker. Every message
sent after that queued behind a spinner for hours. Production does not have
this problem: there the worker *is* the container's process, and `restart:
unless-stopped` brings it back. This gives the dev loop the same guarantee.

Written against `watchfiles.watch` rather than wrapping its CLI in a shell
loop: the CLI stops its child by signalling that one pid, so a shell in
between would swallow the signal and orphan a second worker on every reload.

A worker that exits within `_CRASH_WINDOW_SECONDS` of starting is *not*
restarted until the next change. That is broken code — a syntax error, an
import that fails — and restarting it every second would bury the traceback
the next edit is meant to fix.
"""

import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import FrameType

from watchfiles import PythonFilter, watch

from app.logging import configure_logging, get_logger

logger = get_logger(__name__)

_COMMAND = [sys.executable, "-m", "app.worker"]
_WATCHED = Path(__file__).resolve().parents[1]  # app/
_CRASH_WINDOW_SECONDS = 5.0
# Docker's own budget between SIGTERM and SIGKILL. The worker uses it to put
# whatever it was running back on the queue; see app/worker/shutdown.py.
_STOP_TIMEOUT_SECONDS = 10


def _start() -> tuple[subprocess.Popen[bytes], float]:
    # A fixed argv built from this interpreter's own path: no shell, and
    # nothing in it comes from outside the process.
    return subprocess.Popen(_COMMAND), time.monotonic()  # noqa: S603


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=_STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        logger.warning("worker did not stop in time", timeout_seconds=_STOP_TIMEOUT_SECONDS)
        process.kill()
        process.wait()


def main() -> None:
    configure_logging()

    stop = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, request_stop)

    process, started = _start()
    waiting_for_change = False
    try:
        # A tick every second even with nothing changed — an empty set — which
        # is what lets a dead worker be noticed between edits at all.
        for changes in watch(
            _WATCHED,
            watch_filter=PythonFilter(),
            stop_event=stop,
            rust_timeout=1000,
            yield_on_timeout=True,
        ):
            if changes:
                logger.info("code changed, restarting worker", files=len(changes))
                _stop(process)
                process, started = _start()
                waiting_for_change = False
            elif not waiting_for_change and process.poll() is not None:
                uptime = time.monotonic() - started
                if uptime < _CRASH_WINDOW_SECONDS:
                    logger.error(
                        "worker exited on startup, waiting for a code change",
                        exit_code=process.returncode,
                    )
                    waiting_for_change = True
                else:
                    logger.warning(
                        "worker died, restarting",
                        exit_code=process.returncode,
                        uptime_seconds=round(uptime),
                    )
                    process, started = _start()
    finally:
        _stop(process)


if __name__ == "__main__":
    main()
