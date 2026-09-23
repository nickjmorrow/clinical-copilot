"""`python -m app.seed --from <synthea csv dir>`, optionally `--reset`.

An entry point on the package rather than a `if __name__ == "__main__"` at the
bottom of a module, matching `app/worker/`: importing the seed package must
never write anything.

Thin on purpose — resolve the path, open a session, call the service, report.
The logic is in `services/seed_service.py` so the integration tests can call
it directly.

The export is not checked into the repository (about 380 MB of CSV, regenerable).
`scripts/generate-synthea.sh` produces one; `SYNTHEA_CSV_DIR` in the
environment or `--from` on the command line says where it is.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import settings
from app.db import SessionFactory
from app.logging import configure_logging, get_logger
from app.services import seed_service

logger = get_logger(__name__)


async def _run(*, source: Path, reset: bool) -> None:
    async with SessionFactory() as session:
        summary = await seed_service.seed_all(session, source=source, reset=reset)

    if summary.skipped:
        logger.info("nothing to do", hint="pass --reset to reload")


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Load a Synthea CSV export.")
    parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=settings.synthea_csv_dir,
        help="directory containing patients.csv, medications.csv, observations.csv "
        "(default: $SYNTHEA_CSV_DIR)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete the loaded dataset first (query_audit is never touched)",
    )
    arguments = parser.parse_args()

    if arguments.source is None:
        logger.error("no export given", hint="pass --from <dir> or set SYNTHEA_CSV_DIR")
        sys.exit(2)

    asyncio.run(_run(source=arguments.source, reset=arguments.reset))


main()
