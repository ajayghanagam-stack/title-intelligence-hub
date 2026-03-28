# Wrapper to expose app for supervisor which expects server:app
from app.main import app

__all__ = ["app"]
