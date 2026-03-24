"""Shared rate limiter instance.

Single Limiter used by both the auth routes (decorator) and the FastAPI app
(app.state.limiter + exception handler).  Avoids the dual-instance anti-pattern.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
