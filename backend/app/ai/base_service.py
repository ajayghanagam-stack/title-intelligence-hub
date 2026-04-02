"""Multi-provider AI service using litellm.

Supports Gemini 2.5 Flash (default) and Claude Sonnet 4 as AI providers.
Provider selection is controlled by the AI_PROVIDER config setting.
Gemini-specific code lives in gemini_provider.py, Claude in claude_provider.py.
"""

import os
import uuid
import asyncio
import json
import logging
import re
from typing import Any

import litellm

from app.config import get_settings

logger = logging.getLogger(__name__)

# Timeout for a single AI API call (120 seconds)
AI_CALL_TIMEOUT = 120

# Default model (Gemini) — kept for backward compatibility with imports
MODEL = "gemini/gemini-2.5-flash"

# Suppress litellm debug output (including raw PDF bytes in request payloads)
litellm.set_verbose = False
litellm.suppress_debug_info = True
for _ll_name in ("LiteLLM", "LiteLLM Proxy", "LiteLLM Router", "litellm", "litellm.llms"):
    _ll = logging.getLogger(_ll_name)
    _ll.setLevel(logging.WARNING)
    _ll.handlers = [h for h in _ll.handlers if h.level > logging.INFO]


def _get_model_for_provider(provider: str) -> str:
    """Return the litellm model string for the given provider.

    For hybrid mode, returns the Gemini model (used as the default/vision model).
    Claude model is accessed via _get_claude_model() for the extraction pass.
    """
    if provider == "claude":
        from app.ai.claude_provider import CLAUDE_MODEL
        return CLAUDE_MODEL
    # Both "gemini" and "hybrid" use Gemini as the primary/vision model
    return "gemini/gemini-2.5-flash"


def _get_claude_model() -> str:
    """Return the Claude model string regardless of provider setting.

    Used by hybrid mode for the extraction pass.
    """
    from app.ai.claude_provider import CLAUDE_MODEL
    return CLAUDE_MODEL


def _extract_json_text(raw: str | None) -> str:
    """Extract clean JSON from an AI response that may be wrapped in markdown fences or contain trailing junk."""
    text = (raw or "").strip()
    if not text:
        return ""
    # Strip markdown code fences
    if text.startswith("```"):
        first_nl = text.index("\n") if "\n" in text else len(text)
        text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    # Find the outermost JSON object/array boundaries
    start = -1
    brace = None
    for i, ch in enumerate(text):
        if ch in ('{', '['):
            start = i
            brace = '}' if ch == '{' else ']'
            break
    if start == -1:
        return text  # no JSON structure found, return as-is for error reporting
    # Walk backwards from end to find closing brace
    end = -1
    for i in range(len(text) - 1, start, -1):
        if text[i] == brace:
            end = i
            break
    if end == -1:
        return text
    return text[start:end + 1]


def _parse_json_robust(text: str) -> dict | list:
    """Parse JSON with automatic repair for common LLM output issues.

    Tries strict parse first, then uses iterative error-position repair:
    at each JSONDecodeError position, inserts the likely missing character
    (comma, closing bracket, etc.) and retries. Handles trailing commas,
    missing commas, and truncated output.
    """
    if not text:
        return {}

    # Attempt 1: strict parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: regex-based fixes
    fixed = text
    # Fix trailing commas  (,} or ,])
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    # Fix missing commas between adjacent structures
    fixed = re.sub(r'}\s*{', '}, {', fixed)
    fixed = re.sub(r']\s*\[', '], [', fixed)
    fixed = re.sub(r'}\s*\[', '}, [', fixed)
    fixed = re.sub(r']\s*{', '], {', fixed)
    # Missing comma after string value before next key:  "value"  "key"  →  "value", "key"
    # Also handles:  "value"\n"key"
    fixed = re.sub(r'"\s*\n\s*"', '", "', fixed)
    # null/true/false/number followed by "key" without comma
    fixed = re.sub(r'(null|true|false|\d+)\s*\n\s*"', r'\1, "', fixed)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Attempt 3: iterative error-position repair (up to 20 fixes)
    repaired = fixed
    for _ in range(20):
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            pos = e.pos or 0
            msg = e.msg
            if "Expecting ',' delimiter" in msg:
                # Insert missing comma at error position
                repaired = repaired[:pos] + ',' + repaired[pos:]
            elif "Expecting ':' delimiter" in msg:
                repaired = repaired[:pos] + ':' + repaired[pos:]
            elif "Expecting value" in msg and pos < len(repaired):
                # Likely trailing comma before ] or } — remove char before pos
                if pos > 0 and repaired[pos - 1] == ',':
                    repaired = repaired[:pos - 1] + repaired[pos:]
                else:
                    break  # can't fix
            else:
                break  # unknown error type

    # Attempt 4: close unclosed braces/brackets
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass
    open_braces = repaired.count('{') - repaired.count('}')
    open_brackets = repaired.count('[') - repaired.count(']')
    if open_braces > 0 or open_brackets > 0:
        patched = repaired.rstrip().rstrip(',')
        patched += ']' * max(0, open_brackets)
        patched += '}' * max(0, open_braces)
        try:
            return json.loads(patched)
        except json.JSONDecodeError:
            pass

    # Attempt 5: parse longest valid prefix
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(repaired)
        logger.warning("AI JSON response truncated — parsed partial result")
        return obj
    except json.JSONDecodeError:
        pass

    # All repairs failed — raise with original error for diagnostics
    return json.loads(text)


_configured_providers: set[str] = set()


def _ensure_configured(provider: str | None = None):
    """Configure the active AI provider's API keys.

    Args:
        provider: Optional specific provider to configure on demand
                  (e.g. "claude" for a chat agent override while main provider is gemini).
                  When None, configures the main AI_PROVIDER from settings.
    """
    global _configured_providers
    settings = get_settings()

    # Determine which providers need configuring
    providers_needed: set[str] = set()
    main = settings.AI_PROVIDER

    if not _configured_providers:
        # First call — configure the main provider(s)
        if main == "hybrid":
            providers_needed.update({"gemini", "claude"})
        else:
            providers_needed.add(main)

    # Additionally configure an explicit override provider
    if provider and provider not in _configured_providers:
        providers_needed.add(provider)

    for p in providers_needed:
        if p in _configured_providers:
            continue
        if p == "claude":
            from app.ai.claude_provider import configure_claude
            configure_claude(settings)
        elif p == "gemini":
            from app.ai.gemini_provider import configure_gemini
            configure_gemini(settings)
        _configured_providers.add(p)


class BaseAIService:
    """Base class for AI services. Each micro app subclasses this.

    Dispatches structured output calls to the appropriate provider module
    based on the AI_PROVIDER config setting. Shared methods (call_haiku,
    call_with_tools, call_streaming) work with both providers via litellm.
    """

    def __init__(self, org_id: uuid.UUID, role: str = "default", provider_override: str | None = None):
        _ensure_configured(provider_override)
        self.org_id = org_id
        settings = get_settings()
        self._provider = provider_override or settings.AI_PROVIDER
        self.model = _get_model_for_provider(self._provider)

    async def call_haiku(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        retries: int = 3,
        temperature: float = 0.0,
    ) -> str:
        """Call LLM with retry logic and timeout. Returns text response."""
        for attempt in range(retries):
            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(
                        model=self.model,
                        messages=[{"role": "system", "content": system_prompt}] + messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                    timeout=AI_CALL_TIMEOUT,
                )
                return response.choices[0].message.content
            except asyncio.TimeoutError:
                logger.warning(f"AI call timed out (attempt {attempt + 1}/{retries})")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            except Exception as e:
                logger.warning(f"AI call failed (attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

    async def call_haiku_structured(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
        retries: int = 3,
        temperature: float = 0.0,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Call LLM with tool_use pattern for structured output."""
        # Convert Anthropic tool format to OpenAI/litellm format if needed
        converted_tools = _convert_tools(tools)
        effective_timeout = timeout or AI_CALL_TIMEOUT

        for attempt in range(retries):
            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(
                        model=self.model,
                        messages=[{"role": "system", "content": system_prompt}] + messages,
                        tools=converted_tools,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                    timeout=effective_timeout,
                )
                # Extract tool call result
                message = response.choices[0].message
                if message.tool_calls:
                    tool_call = message.tool_calls[0]
                    args = tool_call.function.arguments
                    if isinstance(args, str):
                        return json.loads(args)
                    return args
                return {}
            except asyncio.TimeoutError:
                logger.warning(f"AI structured call timed out (attempt {attempt + 1}/{retries})")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise
            except Exception as e:
                logger.warning(f"AI structured call failed (attempt {attempt + 1}/{retries}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise

    async def call_json_structured(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any],
        max_tokens: int = 1024,
        retries: int = 3,
        temperature: float = 0.0,
        timeout: int | None = None,
        return_usage: bool = False,
    ) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
        """Call LLM with structured JSON output.

        Dispatches to the appropriate provider:
        - Gemini: native JSON schema response format (or google-genai SDK for PDF blocks)
        - Claude: forced tool_use with cache_control for prompt caching

        When return_usage=True, returns (result_dict, usage_dict) tuple.
        """
        if self._provider == "claude":
            from app.ai.claude_provider import call_json_structured_claude
            return await call_json_structured_claude(
                model=self.model,
                system_prompt=system_prompt,
                messages=messages,
                json_schema=json_schema,
                max_tokens=max_tokens,
                retries=retries,
                temperature=temperature,
                timeout=timeout,
                return_usage=return_usage,
            )

        # Both "gemini" and "hybrid" use Gemini for the default structured call
        from app.ai.gemini_provider import call_json_structured_gemini
        return await call_json_structured_gemini(
            model=self.model,
            system_prompt=system_prompt,
            messages=messages,
            json_schema=json_schema,
            max_tokens=max_tokens,
            retries=retries,
            temperature=temperature,
            timeout=timeout,
            return_usage=return_usage,
        )

    async def call_json_structured_claude(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any],
        max_tokens: int = 1024,
        retries: int = 3,
        temperature: float = 0.0,
        timeout: int | None = None,
        return_usage: bool = False,
    ) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
        """Call Claude specifically for structured JSON output.

        Used by hybrid mode's extraction pass. Always routes to Claude
        regardless of the AI_PROVIDER setting.
        """
        from app.ai.claude_provider import call_json_structured_claude as _claude_call
        claude_model = _get_claude_model()
        return await _claude_call(
            model=claude_model,
            system_prompt=system_prompt,
            messages=messages,
            json_schema=json_schema,
            max_tokens=max_tokens,
            retries=retries,
            temperature=temperature,
            timeout=timeout,
            return_usage=return_usage,
        )

    async def create_context_cache(
        self,
        system_prompt: str,
        json_schema: dict[str, Any],
        ttl_seconds: int = 600,
    ) -> str | None:
        """Create a context cache for the system prompt + schema.

        - Gemini: server-side cache via google-genai SDK
        - Claude: returns None (prompt caching is implicit via cache_control blocks)
        """
        if self._provider == "claude":
            # Claude uses implicit prompt caching via cache_control blocks
            # in call_json_structured_claude — no explicit cache creation needed
            return None

        # Both "gemini" and "hybrid" use Gemini context caching for the vision pass
        from app.ai.gemini_provider import create_context_cache_gemini
        return await create_context_cache_gemini(
            system_prompt=system_prompt,
            json_schema=json_schema,
            ttl_seconds=ttl_seconds,
        )

    async def call_json_structured_cached(
        self,
        cache_name: str,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any],
        max_tokens: int = 1024,
        retries: int = 3,
        temperature: float = 0.0,
        timeout: int | None = None,
        return_usage: bool = False,
    ) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
        """Call LLM with a cached context.

        - Gemini: uses google-genai SDK with cached_content parameter
        - Claude: falls back to call_json_structured (cache_control is implicit)
        """
        if self._provider == "claude":
            # Claude's prompt caching is handled implicitly in call_json_structured_claude
            # via cache_control blocks — no separate cached call method needed.
            # The system_prompt is not available here, but the examiner's fallback
            # path provides it. We need to route through call_json_structured which
            # will include cache_control automatically.
            from app.ai.claude_provider import call_json_structured_claude
            from app.micro_apps.title_intelligence.ai.title_examiner_agent import SYSTEM_PROMPT
            return await call_json_structured_claude(
                model=self.model,
                system_prompt=SYSTEM_PROMPT,
                messages=messages,
                json_schema=json_schema,
                max_tokens=max_tokens,
                retries=retries,
                temperature=temperature,
                timeout=timeout,
                return_usage=return_usage,
            )

        # Both "gemini" and "hybrid" use Gemini cached context for the vision pass
        from app.ai.gemini_provider import call_json_structured_cached_gemini
        return await call_json_structured_cached_gemini(
            cache_name=cache_name,
            messages=messages,
            json_schema=json_schema,
            max_tokens=max_tokens,
            retries=retries,
            temperature=temperature,
            timeout=timeout,
            return_usage=return_usage,
        )

    async def call_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        max_steps: int = 10,
        max_tokens: int = 8192,
        temperature: float = 0.0,
        force_first_tool: bool = False,
    ) -> dict[str, Any]:
        """Iterative tool-calling loop matching V2's generateText + maxSteps pattern.

        Args:
            system_prompt: System prompt for the model
            messages: Conversation messages
            tools: Tool definitions (Anthropic format — will be auto-converted)
            tool_handlers: Dict mapping tool names to async handler functions
            max_steps: Maximum number of tool-calling iterations
            max_tokens: Max tokens per response
            temperature: LLM temperature (0.0 for deterministic)
            force_first_tool: If True, use tool_choice="required" on first step
                to guarantee the model calls at least one tool before answering.

        Returns:
            Final response dict with "text" and/or "tool_results" keys
        """
        converted_tools = _convert_tools(tools)
        working_messages = [{"role": "system", "content": system_prompt}] + list(messages)

        for step in range(max_steps):
            # Force tool usage on first step if requested; auto after that
            tc = "required" if (force_first_tool and step == 0) else "auto"

            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(
                        model=self.model,
                        messages=working_messages,
                        tools=converted_tools,
                        tool_choice=tc,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ),
                    timeout=AI_CALL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Tool call step {step + 1} timed out")
                raise

            message = response.choices[0].message

            if not message.tool_calls:
                # No more tool calls — return final text response
                return {"text": message.content or "", "steps": step + 1}

            # Append assistant message with tool calls
            working_messages.append(message.model_dump())

            # Execute each tool call
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments) if isinstance(
                        tool_call.function.arguments, str
                    ) else tool_call.function.arguments
                except json.JSONDecodeError:
                    args = {}

                handler = tool_handlers.get(tool_name)
                if handler:
                    try:
                        result = await handler(**args)
                        result_str = json.dumps(result) if not isinstance(result, str) else result
                    except Exception as e:
                        logger.warning(f"Tool {tool_name} failed: {e}")
                        result_str = json.dumps({"error": str(e)})
                else:
                    result_str = json.dumps({"error": f"Unknown tool: {tool_name}"})

                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })

            logger.info(f"Tool call step {step + 1}: executed {len(message.tool_calls)} tools")

        # Hit max steps — return whatever we have
        logger.warning(f"Hit max_steps ({max_steps}) in tool-calling loop")
        return {"text": "", "steps": max_steps}

    async def call_with_web_search(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        result_tool_schema: dict[str, Any],
        result_tool_name: str = "submit_research_results",
        result_tool_description: str = "Submit structured research results",
        max_web_searches: int = 15,
        max_tokens: int = 16384,
        temperature: float = 0.0,
        timeout: int = 300,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        """Call Claude with web search + structured result tool.

        Uses Anthropic SDK directly for server-side web_search tool.
        Returns (structured_result, citations) tuple.
        """
        from app.ai.claude_provider import call_with_web_search_claude, configure_claude
        settings = get_settings()
        configure_claude(settings)

        return await call_with_web_search_claude(
            system_prompt=system_prompt,
            messages=messages,
            result_tool_schema=result_tool_schema,
            result_tool_name=result_tool_name,
            result_tool_description=result_tool_description,
            max_web_searches=max_web_searches,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )

    async def call_streaming(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 2048,
    ):
        """Stream LLM response. Yields text chunks.

        Usage:
            async for chunk in service.call_streaming(prompt, messages):
                yield chunk
        """
        _ensure_configured()
        response = await litellm.acompletion(
            model=self.model,
            messages=[{"role": "system", "content": system_prompt}] + messages,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-style tool definitions to OpenAI/litellm format.

    Anthropic format: {"name": "...", "description": "...", "input_schema": {...}}
    OpenAI format: {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
    """
    converted = []
    for tool in tools:
        if "type" in tool and tool["type"] == "function":
            # Already in OpenAI format
            converted.append(tool)
        elif "input_schema" in tool:
            # Anthropic format → convert
            converted.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            })
        else:
            # Unknown format, pass through
            converted.append(tool)
    return converted
