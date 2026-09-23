"""The stop flag, and the signal handlers that set it.

Its own module because it is the one piece of worker state that everything else
reads: the turn checks it between events, the drain loop checks it before
claiming, and `run_forever` waits on it. Putting it anywhere else would make
whichever module owned it a dependency of all the others, and the import graph
would close into a cycle.
"""

import asyncio
import contextlib
import signal

# Set by SIGTERM/SIGINT. Every loop that could run for a while consults it.
#
# Docker sends SIGTERM and then waits ten seconds before SIGKILL, so shutdown is
# a budget, not a request: stop claiming immediately, and get whatever is in
# flight back onto the queue rather than leaving it claimed by a process that no
# longer exists. The sweeper is still the backstop for the ungraceful case, but
# it takes `task_stale_seconds` to act and a deploy should not cost a user that.
requested = asyncio.Event()


def install_signal_handlers() -> None:
    """Route SIGTERM and SIGINT into the shutdown event.

    Through the event loop rather than `signal.signal`, so the flag is set
    between awaits instead of in the middle of one. The default SIGTERM
    disposition kills the process outright, which is what leaves a claimed row
    behind with nobody to notice for `task_stale_seconds`.
    """
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(signum, requested.set)
