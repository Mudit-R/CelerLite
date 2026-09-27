import os
import sys

# Ensure project root is in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Ensure serverless environments (Vercel Lambda) write SQLite DB to /tmp
if os.environ.get("VERCEL"):
    os.environ.setdefault("CELERLITE_DATABASE_URL", "sqlite+aiosqlite:////tmp/celerlite_dev.db")
    os.environ.setdefault("CELERLITE_LOG_FORMAT", "text")

from celerlite.api.app import create_app

app = create_app()
