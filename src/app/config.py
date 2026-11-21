"""app.config - environment-driven configuration for the web app.

``load_dotenv()`` runs once at import so ``TITLE`` / ``ARCHIVE_PATH`` /
``PLAYLISTS_PATH`` from ``.env`` are available before the FastAPI app is
built. Everything that reads the environment imports from here instead of
calling ``load_dotenv`` again.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # pick up .env (TITLE, ARCHIVE_PATH, ...) before anything else

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
APP_TITLE = os.getenv("TITLE", "tapedeck")
