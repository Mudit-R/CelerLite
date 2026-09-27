import os
import sys

# Ensure project root is in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Ensure serverless environments write SQLite DB to /tmp
os.environ.setdefault("VERCEL", "1")
os.environ.setdefault("CELERLITE_DATABASE_URL", "sqlite+aiosqlite:////tmp/celerlite_dev.db")
os.environ.setdefault("CELERLITE_LOG_FORMAT", "text")

try:
    from celerlite.api.app import create_app
    app = create_app(serverless=True)
except Exception as e:
    import traceback
    err_str = traceback.format_exc()
    print("FATAL INIT ERROR IN api/index.py:", err_str, file=sys.stderr)
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def fallback(path: str = ""):
        return HTMLResponse(
            f"<h1>Initialization Error</h1><pre>{err_str}</pre>",
            status_code=500,
        )
