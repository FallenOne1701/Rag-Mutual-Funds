"""Railway/Railpack entrypoint — exposes the FastAPI app at the repo root."""

from src.api.main import app

__all__ = ["app"]
