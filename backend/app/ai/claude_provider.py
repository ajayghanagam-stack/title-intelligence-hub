"""Claude-specific AI provider functions.

Handles structured output via forced tool_use pattern with Anthropic prompt
caching (cache_control blocks). Uses litellm for API calls.
Web search uses the Anthropic SDK directly (server tools unsupported by litellm).
"""

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "anthropic/claude-sonnet-4-20250514"
# Direct SDK model name (without litellm prefix)
CLAUDE_SDK_MODEL = "claude-sonnet-4-20250514"


def configure_claude(settings: Any) -> None:
    """Set Anthropic API key in environment for litellm."""
    if settings.ANTHROPIC_API_KEY:
        os.environ["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY


async def call_json_structured_claude(
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
    """Call Claude with forced tool_use for structured JSON output.

    Uses cache_control blocks on the system prompt for Anthropic prompt
    caching — the system prompt (~1,300 tokens) is cached server-side
    for 5 minutes. All subsequent batch calls within a pipeline run
    reuse the cache automatically.

    Args:
        model: The litellm model string (e.g., "anthropic/claude-sonnet-4-20250514").
        system_prompt: System prompt to send (with cache_control for prompt caching).
        messages: User messages.
        json_schema: JSON schema for the structured output.
        max_tokens: Maximum output tokens.
        retries: Number of retry attempts.
        temperature: LLM temperature.
        timeout: Call timeout in seconds.
        return_usage: If True, return (result_dict, usage_dict) tuple.

    Returns:
        Parsed JSON dict, or (dict, usage_dict) if return_usage=True.
    """
    from app.ai.base_service import AI_CALL_TIMEOUT
    import litellm

    effective_timeout = timeout or AI_CALL_TIMEOUT

    # Wrap JSON schema as a forced tool
    tool = {
        "type": "function",
        "function": {
            "name": "examination_results",
            "description": "Submit structured examination results",
            "parameters": json_schema,
        },
    }

    # System prompt with cache_control for Anthropic prompt caching
    system_msg = {
        "role": "system",
        "content": [{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
    }

    for attempt in range(retries):
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=model,
                    messages=[system_msg] + messages,
                    tools=[tool],
                    tool_choice={"type": "function", "function": {"name": "examination_results"}},
                    max_tokens=max_tokens,
                    temperature=temperature,
                ),
                timeout=effective_timeout,
            )

            # Extract JSON from tool call arguments
            message = response.choices[0].message
            if message.tool_calls:
                args = message.tool_calls[0].function.arguments
                parsed = json.loads(args) if isinstance(args, str) else args
            else:
                parsed = {}

            if return_usage:
                usage = {}
                if hasattr(response, "usage") and response.usage:
                    usage = {
                        "input_tokens": getattr(response.usage, "prompt_tokens", None),
                        "output_tokens": getattr(response.usage, "completion_tokens", None),
                    }
                    # Anthropic returns cache_creation_input_tokens and cache_read_input_tokens
                    cache_creation = getattr(response.usage, "cache_creation_input_tokens", None)
                    cache_read = getattr(response.usage, "cache_read_input_tokens", None)
                    if cache_creation is not None:
                        usage["cache_creation_tokens"] = cache_creation
                    if cache_read is not None:
                        usage["cached_tokens"] = cache_read
                return parsed, usage

            return parsed
        except asyncio.TimeoutError:
            logger.warning(f"Claude structured call timed out (attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:
            logger.warning(f"Claude structured call failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise


async def call_with_web_search_claude(
    system_prompt: str,
    messages: list[dict[str, Any]],
    result_tool_schema: dict[str, Any],
    result_tool_name: str = "submit_research_results",
    result_tool_description: str = "Submit structured research results",
    max_web_searches: int = 15,
    max_tokens: int = 16384,
    retries: int = 2,
    temperature: float = 0.0,
    timeout: int = 300,
    model: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Call Claude with web_search server tool + custom result tool.

    Uses the Anthropic SDK directly (not litellm) because server-side tools
    (web_search_20250305) are not supported by litellm.

    Claude autonomously performs web searches, then calls the result tool
    with structured output.

    Args:
        system_prompt: System prompt for research guidance.
        messages: User messages with research context.
        result_tool_schema: JSON schema for the structured result tool.
        result_tool_name: Name of the result submission tool.
        result_tool_description: Description of the result tool.
        max_web_searches: Max number of web searches Claude can perform.
        max_tokens: Max output tokens.
        retries: Number of retry attempts.
        temperature: LLM temperature.
        timeout: Call timeout in seconds.

    Returns:
        (structured_result, citations) tuple where citations is a list of
        {"url": ..., "title": ...} dicts from web search results.
    """
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        raise RuntimeError("anthropic SDK required for web search. Install with: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Required for Claude web search.")

    client = AsyncAnthropic(api_key=api_key)

    tools = [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_web_searches,
        },
        {
            "type": "custom",
            "name": result_tool_name,
            "description": result_tool_description,
            "input_schema": result_tool_schema,
        },
    ]

    # Resolve effective SDK model — strip the "anthropic/" litellm prefix if a
    # caller passes a fully-qualified litellm id. The Anthropic SDK expects a
    # bare model id (e.g. "claude-sonnet-4-6").
    effective_model = (model or CLAUDE_SDK_MODEL).strip()
    if effective_model.startswith("anthropic/"):
        effective_model = effective_model[len("anthropic/"):]

    async def _do_stream() -> Any:
        # Use the streaming API: the Anthropic SDK refuses non-streaming
        # requests whose pre-flight (max_tokens × per-token-time) estimate
        # exceeds 10 minutes. Web-search calls run with max_tokens=24576
        # and on slower-output models like claude-sonnet-4-6 the estimate
        # blows past that ceiling. `messages.stream(...).get_final_message()`
        # returns the same Message object the non-streaming path would
        # have returned, so the rest of the parsing logic is unchanged.
        async with client.messages.stream(
            model=effective_model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
            tools=tools,
        ) as stream:
            return await stream.get_final_message()

    for attempt in range(retries):
        try:
            response = await asyncio.wait_for(_do_stream(), timeout=timeout)

            # Extract structured result from tool use blocks
            structured_result = {}
            citations: list[dict[str, str]] = []

            for block in response.content:
                # Extract tool use result
                if block.type == "tool_use" and block.name == result_tool_name:
                    structured_result = block.input if isinstance(block.input, dict) else {}

                # Extract citations from web search result blocks. The
                # Anthropic SDK exposes results on `block.content` — a list of
                # WebSearchResultBlock — or, on error, a single
                # WebSearchToolResultError object. There is no `search_results`
                # attribute, so previous reads silently produced empty
                # citations even when web search returned hits.
                if block.type == "web_search_tool_result":
                    block_content = getattr(block, "content", None)
                    if isinstance(block_content, list):
                        for search_result in block_content:
                            url = getattr(search_result, "url", "")
                            title = getattr(search_result, "title", "")
                            if url:
                                citations.append({"url": url, "title": title})
                    else:
                        # Error block (e.g. {type: "web_search_tool_result_error", error_code: ...})
                        err_code = getattr(block_content, "error_code", None)
                        if err_code:
                            logger.warning(
                                f"Claude web_search returned error block: {err_code}"
                            )

            # Deduplicate citations by URL
            seen_urls: set[str] = set()
            unique_citations: list[dict[str, str]] = []
            for c in citations:
                if c["url"] not in seen_urls:
                    seen_urls.add(c["url"])
                    unique_citations.append(c)

            return structured_result, unique_citations

        except asyncio.TimeoutError:
            logger.warning(f"Claude web search timed out (attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise
        except Exception as e:
            logger.warning(f"Claude web search failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            raise

    # Should not reach here, but satisfy type checker
    return {}, []
