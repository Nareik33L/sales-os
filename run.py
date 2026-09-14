"""Entry point: apply migrations, then launch the Streamlit app locally.

    python run.py            # migrate + start UI on http://localhost:8501
    python run.py --migrate  # migrate only

Streamlit is pinned to localhost by .streamlit/config.toml (ADR-008).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
APP_ENTRY = ROOT / "app" / "main.py"


def migrate_only() -> None:
    from database.db import connect, migrate

    conn = connect()
    applied = migrate(conn)
    conn.close()
    print(f"database ready; applied migrations: {applied or 'none (up to date)'}")


def main(argv: list[str]) -> int:
    load_dotenv(ROOT / ".env")
    migrate_only()
    if "--migrate" in argv:
        return 0
    if not APP_ENTRY.exists():
        print("app/main.py not built yet — see docs/10-build-plan.md (Phase 2).")
        return 0
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(APP_ENTRY)])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
