"""`python -m app.worker`.

The package has an entry point rather than a `if __name__ == "__main__"` at the
bottom of a module so that the command in both compose files keeps working
unchanged, and so that importing any part of the worker never runs it.
"""

from app.worker.loop import main

main()
