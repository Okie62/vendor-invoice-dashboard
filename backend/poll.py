#!/usr/bin/env python3
"""
Email polling runner — call this from cron or launchd.

Usage:
    python3 poll.py            # Run once
    python3 poll.py --watch    # Run continuously (every POLL_INTERVAL seconds)
"""

import argparse
import logging
import time

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)

from config import POLL_INTERVAL
from ingest import run_ingestion


def main():
    parser = argparse.ArgumentParser(description="Email invoice poller")
    parser.add_argument("--watch", action="store_true",
                        help="Run continuously every POLL_INTERVAL seconds")
    args = parser.parse_args()

    if args.watch:
        while True:
            try:
                run_ingestion()
            except Exception as e:
                logging.error(f"Ingestion error: {e}")
            time.sleep(POLL_INTERVAL)
    else:
        run_ingestion()


if __name__ == "__main__":
    main()
