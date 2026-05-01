"""TSA Claude model resolution helper.

`TA_CLAUDE_MODEL` lets ops bump the model used by every TSA agent without
editing code. Empty string = fall back to BaseAIService's per-provider
default. Bare ids are auto-prefixed with "anthropic/" for litellm.
"""

from app.config import get_settings


def get_ta_claude_model() -> str | None:
    """Return the configured TSA Claude model id, or None if unset.

    - Returns None when `TA_CLAUDE_MODEL` is empty (use the default).
    - Returns the value as-is when it already contains a provider prefix
      (e.g. "anthropic/claude-sonnet-4-6").
    - Otherwise prepends "anthropic/" so litellm routes correctly.
    """
    raw = (get_settings().TA_CLAUDE_MODEL or "").strip()
    if not raw:
        return None
    return raw if "/" in raw else f"anthropic/{raw}"
