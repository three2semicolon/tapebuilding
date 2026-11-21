"""app.server - console-script entry point for ``uv run app``.

Runs the FastAPI app in :mod:`app.main` with uvicorn:

    uv run app

Equivalent to:

    uv run uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", port=8000, reload=True)


if __name__ == "__main__":
    main()
