"""
Startup wrapper that runs the Flask server AND a background email poller thread.
Used on Render so both the web service and email polling share the same disk.
"""
import logging
import os
import sys
import threading
import time
from filelock import FileLock

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger(__name__)

from config import POLL_INTERVAL, DATA_DIR
from ingest import run_ingestion
from server import app, init_db

_poller_started = False
_lock = threading.Lock()

# File lock path — ensures only one poller thread runs even with multiple gunicorn workers
POLLER_LOCK_PATH = str(DATA_DIR / "poller.lock")


def poller_loop():
    """Background thread that polls Gmail for invoices.

    Uses a file lock (#12) so only one poller runs even if gunicorn
    spawns multiple workers.
    """
    init_db()
    time.sleep(10)
    log.info("Email poller thread started — polling every %d seconds", POLL_INTERVAL)
    poller_lock = FileLock(POLLER_LOCK_PATH, timeout=0)
    while True:
        try:
            with poller_lock:
                count = run_ingestion()
                if count > 0:
                    log.info("Poller processed %d email(s)", count)
        except Exception as e:
            if "timeout" in str(e).lower():
                log.debug("Another poller thread holds the lock — skipping cycle")
            else:
                log.error("Poller error: %s", e)
        time.sleep(POLL_INTERVAL)


def start_poller_thread():
    """Start the background email poller thread (if not already running)."""
    global _poller_started
    with _lock:
        if _poller_started:
            return
        _poller_started = True
    poller_thread = threading.Thread(target=poller_loop, daemon=True)
    poller_thread.start()
    log.info("Email poller thread started — polling every %d seconds", POLL_INTERVAL)


# When imported by gunicorn (runner:app), __name__ is "runner", not "__main__".
# Start the poller thread at import time so it runs under gunicorn.
init_db()
start_poller_thread()


if __name__ == "__main__":
    # Run the Flask app directly (local dev)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
