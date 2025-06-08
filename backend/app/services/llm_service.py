"""
LLM Service for handling multiple provider integrations
"""
import json
import logging
from typing import Any

import httpx
from sqlmodel import Session, select

from app.core.encryption import encryption_service
from app.models import LLMSettings, User

logger = logging.getLogger(__name__)


class LLMProvider:
    """Base class for LLM providers"""

    def __init__(self, settings: LLMSettings, api_key: str):
        self.settings = settings
        self.api_key = api_key

    async def generate_response(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """Generate a response from the LLM"""
        raise NotImplementedError

    async def analyze_for_tools(
        self,
        message: str,
        available_tools: list[dict],
        **kwargs
    ) -> dict[str, Any]:
        """Analyze a message to determine which tools should be called"""
        raise NotImplementedError


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider"""

    def __init__(self, settings: LLMSettings, api_key: str):
        super().__init__(settings, api_key)
        self.base_url = "https://api.openai.com/v1"

    async def generate_response(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """Generate response using OpenAI API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens
        }

        # Add tools if provided
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

                return {
                    "success": True,
                    "content": result["choices"][0]["message"]["content"],
                    "tool_calls": result["choices"][0]["message"].get("tool_calls", []),
                    "usage": result.get("usage", {}),
                    "model": result.get("model", self.settings.model)
                }

        except httpx.HTTPError as e:
            logger.error(f"OpenAI API error: {e}")
            return {
                "success": False,
                "error": f"OpenAI API error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"OpenAI provider error: {e}")
            return {
                "success": False,
                "error": f"Provider error: {str(e)}"
            }

    async def analyze_for_tools(
        self,
        message: str,
        available_tools: list[dict],
        **kwargs
    ) -> dict[str, Any]:
        """Analyze message using OpenAI to determine tool usage"""
        if not available_tools:
            return {"requires_tools": False, "tools": [], "reasoning": "No tools available"}

        # Create a system prompt for tool analysis
        system_prompt = f"""You are an AI assistant that analyzes user messages to determine which tools should be called.

Available tools:
{json.dumps(available_tools, indent=2)}

Analyze the user's message and determine:
1. Whether any tools should be called
2. Which specific tools to call and with what parameters
3. The reasoning behind your decisions

Respond with a JSON object containing:
- "requires_tools": boolean
- "tools": array of tool calls with "name" and "parameters"
- "reasoning": string explaining your decision

User message: "{message}"
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message}
        ]

        try:
            result = await self.generate_response(messages)
            if result["success"]:
                # Parse the JSON response
                content = result["content"].strip()
                if content.startswith("```json"):
                    content = content[7:-3].strip()
                elif content.startswith("```"):
                    content = content[3:-3].strip()

                analysis = json.loads(content)
                return analysis
            else:
                return {"requires_tools": False, "tools": [], "reasoning": f"Analysis failed: {result.get('error')}"}

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool analysis JSON: {e}")
            return {"requires_tools": False, "tools": [], "reasoning": "Failed to parse analysis"}
        except Exception as e:
            logger.error(f"Tool analysis error: {e}")
            return {"requires_tools": False, "tools": [], "reasoning": f"Analysis error: {str(e)}"}


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider"""

    def __init__(self, settings: LLMSettings, api_key: str):
        super().__init__(settings, api_key)
        self.base_url = "https://api.anthropic.com/v1"

    async def generate_response(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """Generate response using Anthropic API"""
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }

        # Convert messages to Anthropic format
        system_message = ""
        anthropic_messages = []

        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        payload = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "temperature": self.settings.temperature,
            "messages": anthropic_messages
        }

        if system_message:
            payload["system"] = system_message

        # Add tools if provided (Anthropic format)
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

                content = ""
                tool_calls = []

                for content_block in result["content"]:
                    if content_block["type"] == "text":
                        content += content_block["text"]
                    elif content_block["type"] == "tool_use":
                        tool_calls.append({
                            "id": content_block["id"],
                            "type": "function",
                            "function": {
                                "name": content_block["name"],
                                "arguments": json.dumps(content_block["input"])
                            }
                        })

                return {
                    "success": True,
                    "content": content,
                    "tool_calls": tool_calls,
                    "usage": result.get("usage", {}),
                    "model": result.get("model", self.settings.model)
                }

        except httpx.HTTPError as e:
            logger.error(f"Anthropic API error: {e}")
            return {
                "success": False,
                "error": f"Anthropic API error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Anthropic provider error: {e}")
            return {
                "success": False,
                "error": f"Provider error: {str(e)}"
            }

    async def analyze_for_tools(
        self,
        message: str,
        available_tools: list[dict],
        **kwargs
    ) -> dict[str, Any]:
        """Analyze message using Claude to determine tool usage"""
        # Similar implementation to OpenAI but with Anthropic-specific formatting
        return await self._generic_tool_analysis(message, available_tools)

    async def _generic_tool_analysis(self, message: str, available_tools: list[dict]) -> dict[str, Any]:
        """Generic tool analysis using the LLM"""
        if not available_tools:
            return {"requires_tools": False, "tools": [], "reasoning": "No tools available"}

        system_prompt = f"""You are an AI assistant that analyzes user messages to determine which tools should be called.

Available tools:
{json.dumps(available_tools, indent=2)}

Analyze the user's message and determine:
1. Whether any tools should be called
2. Which specific tools to call and with what parameters
3. The reasoning behind your decisions

Respond with a JSON object containing:
- "requires_tools": boolean
- "tools": array of tool calls with "name" and "parameters"
- "reasoning": string explaining your decision"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Analyze this message for tool usage: {message}"}
        ]

        try:
            result = await self.generate_response(messages)
            if result["success"]:
                content = result["content"].strip()
                if content.startswith("```json"):
                    content = content[7:-3].strip()
                elif content.startswith("```"):
                    content = content[3:-3].strip()

                analysis = json.loads(content)
                return analysis
            else:
                return {"requires_tools": False, "tools": [], "reasoning": f"Analysis failed: {result.get('error')}"}

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool analysis JSON: {e}")
            return {"requires_tools": False, "tools": [], "reasoning": "Failed to parse analysis"}
        except Exception as e:
            logger.error(f"Tool analysis error: {e}")
            return {"requires_tools": False, "tools": [], "reasoning": f"Analysis error: {str(e)}"}


class LLMService:
    """Main LLM service that manages different providers"""

    def __init__(self):
        self.providers = {
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
        }

    def _get_provider(self, settings: LLMSettings) -> LLMProvider | None:
        """Get the appropriate provider for the given settings"""
        if not settings or not settings.is_active:
            return None

        provider_class = self.providers.get(settings.provider)
        if not provider_class:
            logger.error(f"Unsupported provider: {settings.provider}")
            return None

        try:
            # Decrypt API key
            api_key = encryption_service.decrypt(settings.encrypted_api_key)
            return provider_class(settings, api_key)
        except Exception as e:
            logger.error(f"Failed to initialize provider {settings.provider}: {e}")
            return None

    async def get_user_llm_settings(self, user: User, session: Session) -> LLMSettings | None:
        """Get user's LLM settings"""
        statement = select(LLMSettings).where(
            LLMSettings.owner_id == user.id,
            LLMSettings.is_active == True
        )
        return session.exec(statement).first()

    async def generate_response(
        self,
        user: User,
        session: Session,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """Generate a response using the user's preferred LLM"""
        settings = await self.get_user_llm_settings(user, session)
        if not settings:
            return {
                "success": False,
                "error": "No active LLM settings found. Please configure your LLM settings first."
            }

        provider = self._get_provider(settings)
        if not provider:
            return {
                "success": False,
                "error": f"Failed to initialize LLM provider: {settings.provider}"
            }

        return await provider.generate_response(messages, tools, **kwargs)

    async def analyze_for_tools(
        self,
        user: User,
        session: Session,
        message: str,
        available_tools: list[dict],
        **kwargs
    ) -> dict[str, Any]:
        """Analyze a message for tool usage using the user's preferred LLM"""
        settings = await self.get_user_llm_settings(user, session)
        if not settings:
            # Fallback to rule-based analysis if no LLM configured
            return self._fallback_tool_analysis(message, available_tools)

        provider = self._get_provider(settings)
        if not provider:
            # Fallback to rule-based analysis if provider fails
            return self._fallback_tool_analysis(message, available_tools)

        return await provider.analyze_for_tools(message, available_tools, **kwargs)

    def _fallback_tool_analysis(self, message: str, available_tools: list[dict]) -> dict[str, Any]:
        """Fallback rule-based tool analysis when LLM is not available"""
        message_lower = message.lower()

        # Keywords that suggest CRM operations
        crm_keywords = [
            "lead", "leads", "crm", "customer", "customers", "contact", "contacts",
            "prospect", "prospects", "sales", "pipeline", "activity", "call", "email",
            "search", "find", "get", "show", "list", "recent", "latest", "assigned"
        ]

        # Check if message contains CRM-related keywords
        needs_crm = any(keyword in message_lower for keyword in crm_keywords)

        required_tools = []

        if needs_crm:
            # Find CRM-related tools
            for tool in available_tools:
                tool_name = tool.get("name", "").lower()
                if "crm" in tool_name or "lead" in tool_name or "customer" in tool_name:
                    if any(word in message_lower for word in ["search", "find"]):
                        if "search" in tool_name:
                            required_tools.append({
                                "name": tool["name"],
                                "parameters": self._extract_search_params(message)
                            })
                    elif any(word in message_lower for word in ["recent", "latest", "list"]):
                        if "get" in tool_name and "recent" in tool_name:
                            required_tools.append({
                                "name": tool["name"],
                                "parameters": {"limit": 5}
                            })

        return {
            "requires_tools": len(required_tools) > 0,
            "tools": required_tools,
            "reasoning": f"Rule-based analysis: {'Found CRM keywords' if needs_crm else 'No relevant keywords found'}"
        }

    def _extract_search_params(self, message: str) -> dict[str, Any]:
        """Extract search parameters from message"""
        import re

        # Look for quoted terms
        quoted = re.search(r'"([^"]*)"', message)
        if quoted:
            return {"query": quoted.group(1)}

        # Look for terms after "for", "named", "with"
        patterns = [
            r'(?:for|named|with)\s+([a-zA-Z0-9@._-]+)',
            r'email\s+([a-zA-Z0-9@._-]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return {"query": match.group(1).strip()}

        return {"query": ""}


# Global LLM service instance
llm_service = LLMService()
