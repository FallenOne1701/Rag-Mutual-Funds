"""Railway/Railpack entrypoint — exposes the FastAPI app at the repo root."""

from __future__ import annotations

import os

from src.api.main import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
