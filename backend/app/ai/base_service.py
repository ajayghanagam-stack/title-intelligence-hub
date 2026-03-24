"""Multi-provider AI service using litellm.

Supports Anthropic (direct), Bedrock, OpenAI, and Azure via the litellm unified SDK.
AI_PLATFORM setting selects the provider; existing agents continue to call the same methods.
"""

import uuid
import asyncio
import json
import logging
from typing import Any

import litellm

from app.config import get_settings

logger = logging.getLogger(__name__)

# Timeout for a single AI API call (120 seconds)
AI_CALL_TIMEOUT = 120

# Model mapping per platform and role
PLATFORM_MODELS = {
    "anthropic": {
        "default": "claude-haiku-4-5-20251001",
        "strong": "claude-sonnet-4-20250514",
    },
    "bedrock": {
        "default": "bedrock/us.anthropic.claude-3-5-haiku-20241022-v1:0",
        "strong": "bedrock/us.anthropic.claude-3-5-sonnet-20241022-v2:0",
    },
    "openai": {
        "default": "gpt-4o-mini",
        "strong": "gpt-4o",
    },
    "azure": {
        "default": "azure/gpt-4o-mini",
        "strong": "azure/gpt-4o",
    },
}

# Suppress litellm debug output
litellm.set_verbose = False


def _configure_litellm():
    """Set litellm API keys from settings."""
    settings = get_settings()
    if settings.ANTHROPIC_API_KEY:
        litellm.api_key = settings.ANTHROPIC_API_KEY
    if settings.OPENAI_API_KEY:
        import os
        os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    if settings.AZURE_API_KEY:
        import os
        os.environ["AZURE_API_KEY"] = settings.AZURE_API_KEY
        os.environ["AZURE_API_BASE"] = settings.AZURE_API_BASE
        os.environ["AZURE_API_VERSION"] = settings.AZURE_API_VERSION


_configured = False


def _ensure_configured():
    global _configured
    if not _configured:
        _configure_litellm()
        _configured = True


class BaseAIService:
    """Base class for AI services. Each micro app subclasses this.

    Uses litellm for multi-provider support. Provider is selected via AI_PLATFORM setting.
    """

    def __init__(self, org_id: uuid.UUID, role: str = "default"):
        _ensure_configured()
        self.org_id = org_id
        settings = get_settings()
        platform = settings.AI_PLATFORM
        models = PLATFORM_MODELS.get(platform, PLATFORM_MODELS["anthropic"])
        self.model = models.get(role, models["default"])

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
    ) -> dict[str, Any]:
        """Call LLM with tool_use pattern for structured output."""
        # Convert Anthropic tool format to OpenAI/litellm format if needed
        converted_tools = _convert_tools(tools)

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
                    timeout=AI_CALL_TIMEOUT,
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

    async def call_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Any],
        max_steps: int = 10,
        max_tokens: int = 8192,
        temperature: float = 0.0,
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

        Returns:
            Final response dict with "text" and/or "tool_results" keys
        """
        converted_tools = _convert_tools(tools)
        working_messages = [{"role": "system", "content": system_prompt}] + list(messages)

        for step in range(max_steps):
            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(
                        model=self.model,
                        messages=working_messages,
                        tools=converted_tools,
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
