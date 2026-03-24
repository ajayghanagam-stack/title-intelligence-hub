def __getattr__(name):
    if name == "micro_app":
        from app.micro_apps.title_intelligence.app import micro_app
        return micro_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["micro_app"]
