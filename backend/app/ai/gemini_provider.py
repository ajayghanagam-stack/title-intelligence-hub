"""Gemini-specific AI provider functions.

Handles native JSON schema response format, google-genai SDK integration
for context caching and PDF content blocks, and Gemini API configuration.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# google-genai model name (without litellm prefix)
GEMINI_MODEL = "gemini/gemini-2.5-flash"
GENAI_MODEL = "gemini-2.5-flash"

# Module-level cache for Gemini context caching handles
# Key: hash of (system_prompt + schema_json), Value: cache resource name
_context_cache_map: dict[str, str] = {}


def configure_gemini(settings: Any) -> None:
    """Set Gemini API key/Vertex AI credentials in environment for litellm."""
    if settings.VERTEX_AI:
        # Vertex AI: litellm uses GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_REGION
        os.environ["GOOGLE_CLOUD_PROJECT"] = settings.GOOGLE_CLOUD_PROJECT
        os.environ["GOOGLE_CLOUD_REGION"] = settings.GOOGLE_CLOUD_REGION
        logger.info(
            f"Configured Vertex AI: project={settings.GOOGLE_CLOUD_PROJECT}, "
            f"region={settings.GOOGLE_CLOUD_REGION}"
        )
    elif settings.GOOGLE_API_KEY:
        os.environ["GEMINI_API_KEY"] = settings.GOOGLE_API_KEY


def _get_litellm_model() -> str:
    """Return the litellm model string based on Vertex AI or AI Studio."""
    settings = get_settings()
    if settings.VERTEX_AI:
        return "vertex_ai/gemini-2.5-flash"
    return GEMINI_MODEL


def get_genai_client() -> Any | None:
    """Get or create a google-genai client for context caching."""
    settings = get_settings()
    try:
        from google import genai
        if settings.VERTEX_AI:
            return genai.Client(
                vertexai=True,
                project=settings.GOOGLE_CLOUD_PROJECT,
                location=settings.GOOGLE_CLOUD_REGION,
            )
        return genai.Client(api_key=settings.GOOGLE_API_KEY)
    except ImportError:
        logger.warning("google-genai not installed — context caching unavailable")
        return None


def messages_contain_pdf(messages: list[dict[str, Any]]) -> bool:
    """Check if any message contains a PDF content block."""
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "pdf":
                    return True
    return False


def _convert_genai_contents(messages: list[dict[str, Any]]) -> list:
    """Convert messages to google-genai Content format.

    Handles text, image_url (data URL), and PDF content blocks.
    """
    from google.genai import types

    contents: list[types.Content] = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        if isinstance(msg["content"], str):
            contents.append(types.Content(
                role=role,
                parts=[types.Part.from_text(text=msg["content"])],
            ))
        elif isinstance(msg["content"], list):
            parts: list[types.Part] = []
            for block in msg["content"]:
                if block.get("type") == "text":
                    parts.append(types.Part.from_text(text=block["text"]))
                elif block.get("type") == "pdf":
                    parts.append(types.Part.from_bytes(
                        data=block["pdf"]["data"],
                        mime_type="application/pdf",
                    ))
                elif block.get("type") == "image_url":
                    url = block["image_url"]["url"]
                    if url.startswith("data:"):
                        header, b64_data = url.split(",", 1)
                        mime_type = header.split(":")[1].split(";")[0]
                        parts.append(types.Part.from_bytes(
                            data=base64.b64decode(b64_data),
                            mime_type=mime_type,
                        ))
            contents.append(types.Content(role=role, parts=parts))
    return contents


async def call_json_structured_gemini(
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    json_schema: dict[str, Any],
    max_tokens: int = 1024,
    retries: int = 3,
    temperature: float = 0.0,
    timeout: int | None = None,
    return_usage: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Call Gemini with native JSON schema response format via litellm.

    When messages contain PDF content blocks, routes through google-genai
    SDK directly since litellm doesn't support PDF content type.
    """
    from app.ai.base_service import _extract_json_text, _parse_json_robust, AI_CALL_TIMEOUT

    # PDF content blocks → route through google-genai SDK
    if messages_contain_pdf(messages):
        return await _call_genai_direct(
            system_prompt, messages, json_schema, max_tokens,
            retries, temperature, timeout, return_usage,
        )

    import litellm
    effective_timeout = timeout or AI_CALL_TIMEOUT

    for attempt in range(retries):
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=model,
                    messages=[{"role": "system", "content": system_prompt}] + messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "examination_results",
                            "schema": json_schema,
                        },
                    },
                ),
                timeout=effective_timeout,
            )
            content = _extract_json_text(response.choices[0].message.content)
            parsed = _parse_json_robust(content) if content else {}

            if return_usage:
                usage = {}
                if hasattr(response, "usage") and response.usage:
                    usage = {
                        "input_tokens": getattr(response.usage, "prompt_tokens", None),
                        "output_tokens": getattr(response.usage, "completion_tokens", None),
                    }
                return parsed, usage

            return parsed
        except asyncio.TimeoutError:
            logger.warning(f"AI JSON structured call timed out (attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:
            logger.warning(f"AI JSON structured call failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise


async def _call_genai_direct(
    system_prompt: str,
    messages: list[dict[str, Any]],
    json_schema: dict[str, Any],
    max_tokens: int = 1024,
    retries: int = 3,
    temperature: float = 0.0,
    timeout: int | None = None,
    return_usage: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Call google-genai SDK directly for messages containing PDF blocks."""
    from app.ai.base_service import _extract_json_text, _parse_json_robust, AI_CALL_TIMEOUT
    from google.genai import types

    effective_timeout = timeout or AI_CALL_TIMEOUT

    for attempt in range(retries):
        try:
            client = get_genai_client()
            if client is None:
                raise RuntimeError("google-genai client unavailable")

            contents = _convert_genai_contents(messages)

            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=GENAI_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                        seed=0,
                        response_mime_type="application/json",
                        response_schema=json_schema,
                    ),
                ),
                timeout=effective_timeout,
            )

            raw_text = _extract_json_text(response.text)
            parsed = _parse_json_robust(raw_text) if raw_text else {}

            if return_usage:
                usage = {}
                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    usage = {
                        "input_tokens": getattr(response.usage_metadata, "prompt_token_count", None),
                        "output_tokens": getattr(response.usage_metadata, "candidates_token_count", None),
                    }
                return parsed, usage

            return parsed
        except json.JSONDecodeError as e:
            snippet = (response.text or "")[:500]
            logger.warning(
                f"AI genai JSON parse failed (attempt {attempt + 1}/{retries}): {e}\n"
                f"  Response snippet: {snippet!r}"
            )
            # JSON parse errors from truncated output won't be fixed by retrying
            # the same input. Return empty dict rather than blocking the pipeline.
            if attempt >= retries - 1:
                logger.warning("All JSON parse attempts failed — returning empty result for this batch")
                if return_usage:
                    return {}, {}
                return {}
            await asyncio.sleep(2 ** attempt)
            continue
        except asyncio.TimeoutError:
            logger.warning(f"AI genai direct call timed out (attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:
            logger.warning(f"AI genai direct call failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise


async def create_context_cache_gemini(
    system_prompt: str,
    json_schema: dict[str, Any],
    ttl_seconds: int = 600,
) -> str | None:
    """Create a Gemini context cache for a system prompt + schema.

    The cache is stored server-side by Google and referenced by name
    in subsequent calls.

    Returns:
        Cache resource name (e.g., "cachedContents/abc123") or None if caching fails.
    """
    schema_json = json.dumps(json_schema, sort_keys=True)
    cache_key = hashlib.sha256(
        (system_prompt + schema_json + GENAI_MODEL).encode()
    ).hexdigest()

    # Check in-memory cache map first
    if cache_key in _context_cache_map:
        logger.debug(f"Context cache hit (in-memory): {cache_key[:12]}")
        return _context_cache_map[cache_key]

    try:
        client = get_genai_client()
        if client is None:
            return None

        from google.genai import types

        cache = await client.aio.caches.create(
            model=GENAI_MODEL,
            config=types.CreateCachedContentConfig(
                system_instruction=system_prompt,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(
                            text=f"Output JSON schema:\n{schema_json}"
                        )],
                    ),
                ],
                ttl=f"{ttl_seconds}s",
            ),
        )

        cache_name = cache.name
        _context_cache_map[cache_key] = cache_name
        logger.info(f"Created Gemini context cache: {cache_name} (TTL={ttl_seconds}s)")
        return cache_name
    except Exception as e:
        logger.warning(f"Failed to create context cache (non-fatal): {e}")
        return None


async def call_json_structured_cached_gemini(
    cache_name: str,
    messages: list[dict[str, Any]],
    json_schema: dict[str, Any],
    max_tokens: int = 1024,
    retries: int = 3,
    temperature: float = 0.0,
    timeout: int | None = None,
    return_usage: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Call Gemini with a cached context (system prompt + schema).

    Uses google-genai SDK directly to leverage the cached_content parameter.
    """
    from app.ai.base_service import _extract_json_text, _parse_json_robust, AI_CALL_TIMEOUT

    effective_timeout = timeout or AI_CALL_TIMEOUT

    for attempt in range(retries):
        try:
            result = await asyncio.wait_for(
                _call_genai_cached(
                    cache_name, messages, json_schema, max_tokens, temperature,
                    return_usage=return_usage,
                ),
                timeout=effective_timeout,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Cached AI call timed out (attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
        except json.JSONDecodeError as e:
            # JSON parse errors on cached calls won't be fixed by retrying —
            # same cache + same input = same broken output. Fail fast to
            # trigger fallback to uncached path.
            logger.warning(
                f"Cached call returned malformed JSON — skipping retries, "
                f"falling back to uncached: {e}"
            )
            raise
        except Exception as e:
            err_str = str(e)
            logger.warning(f"Cached AI call failed (attempt {attempt + 1}/{retries}): {e}")
            # If cache expired, invalidate the in-memory entry so it gets recreated
            if "expired" in err_str.lower():
                for key, val in list(_context_cache_map.items()):
                    if val == cache_name:
                        del _context_cache_map[key]
                        logger.info(f"Invalidated expired cache entry: {cache_name}")
                        break
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise


async def _call_genai_cached(
    cache_name: str,
    messages: list[dict[str, Any]],
    json_schema: dict[str, Any],
    max_tokens: int,
    temperature: float,
    return_usage: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Execute a single cached call via google-genai SDK."""
    from app.ai.base_service import _extract_json_text, _parse_json_robust
    from google.genai import types

    client = get_genai_client()
    if client is None:
        raise RuntimeError("google-genai client unavailable")

    contents = _convert_genai_contents(messages)

    response = await client.aio.models.generate_content(
        model=GENAI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            cached_content=cache_name,
            max_output_tokens=max_tokens,
            temperature=temperature,
            seed=0,
            response_mime_type="application/json",
            response_schema=json_schema,
        ),
    )

    raw_text = _extract_json_text(response.text)
    parsed = _parse_json_robust(raw_text) if raw_text else {}

    if return_usage:
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "input_tokens": getattr(um, "prompt_token_count", None),
                "output_tokens": getattr(um, "candidates_token_count", None),
                "cached_tokens": getattr(um, "cached_content_token_count", None),
            }
        return parsed, usage

    return parsed
