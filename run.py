"""Entry point: apply migrations, then launch the Streamlit app locally.

    python run.py            # migrate + start UI on http://localhost:8501
    python run.py --migrate  # migrate only
    python run.py --demo     # migrate + seed fictional data (does not start Streamlit)

Streamlit is pinned to localhost by .streamlit/config.toml (ADR-008).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from config.loaders import ConfigError, load_all
from core.logging_setup import setup_logging

ROOT = Path(__file__).parent
APP_ENTRY = ROOT / "app" / "main.py"
log = logging.getLogger("salesos.run")


def migrate_only() -> None:
    from database.db import connect, migrate

    conn = connect()
    applied = migrate(conn)
    conn.close()
    print(f"database ready; applied migrations: {applied or 'none (up to date)'}")


def seed_demo_db() -> None:
    from database.db import connect
    from database.seed import seed_demo

    conn = connect()
    try:
        counts = seed_demo(conn)
    finally:
        conn.close()
    summary = ", ".join(f"{table}={n}" for table, n in counts.items())
    print(f"demo data seeded (fictional only): {summary}")
    log.info("demo seed complete: %s", summary)


def main(argv: list[str]) -> int:
    load_dotenv(ROOT / ".env")
    setup_logging()
    try:
        load_all()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        log.error("invalid config: %s", exc)
        return 1
    migrate_only()
    if "--demo" in argv:
        seed_demo_db()
    if "--migrate" in argv or "--demo" in argv:
        return 0
    if not APP_ENTRY.exists():
        print("app/main.py not built yet — see docs/10-build-plan.md (Phase 2).")
        return 0
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(APP_ENTRY)])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
