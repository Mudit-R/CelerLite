import os
import sys

# Ensure project root is in sys.path
root_dir = os.path.abspath(os.path.dirname(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Ensure serverless environments write SQLite DB to /tmp
os.environ.setdefault("VERCEL", "1")
os.environ.setdefault("CELERLITE_DATABASE_URL", "sqlite+aiosqlite:////tmp/celerlite_dev.db")
os.environ.setdefault("CELERLITE_LOG_FORMAT", "text")

from celerlite.api.app import create_app

app = create_app(serverless=True)
