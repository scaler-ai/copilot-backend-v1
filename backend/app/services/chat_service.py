import json
import logging
from datetime import datetime
from typing import Any

from sqlmodel import Session, select

from app.models import ChatConversation, ChatMessageDB, MCPServer, User
from app.services.llm_prompts import LLMPrompts
from app.services.llm_service import llm_service
from app.services.mcp_manager import mcp_manager

logger = logging.getLogger(__name__)


class ChatService:
    """Service for handling chat with LLM and MCP tool integration"""

    def __init__(self):
        self.conversation_history: dict[str, list[dict]] = {}  # Keep for backwards compatibility

    async def process_chat_message(
        self,
        user: User,
        message: str,
        session: Session,
        conversation_id: str | None = None
    ) -> dict[str, Any]:
        """
        Process a chat message with LLM and automatic MCP tool calling

        Args:
            user: Current user
            message: User's message
            session: Database session
            conversation_id: Optional conversation ID for history

        Returns:
            Dict with response and any tool call results
        """
        try:
            # Get user's connected MCP servers
            connected_servers = await self._get_user_connected_servers(user, session)

            # Analyze message for potential tool calls using LLM
            tool_analysis = await llm_service.analyze_for_tools(
                user, session, message, self._format_tools_for_analysis(connected_servers)
            )

            # Execute any identified tools
            tool_results = []
            if tool_analysis.get("requires_tools"):
                # Convert LLM tool analysis to execution format
                execution_tools = await self._prepare_tools_for_execution(
                    tool_analysis["tools"], connected_servers, user, session
                )
                if execution_tools:
                    tool_results = await self._execute_required_tools(
                        execution_tools, user, session
                    )

            # Generate LLM response with context and tool results
            llm_response = await self._generate_llm_response_with_service(
                user, session, message, tool_results, connected_servers, conversation_id
            )

            # Store conversation and messages in database
            if conversation_id:
                # Create or get conversation
                title = message[:50] + "..." if len(message) > 50 else message
                self._get_or_create_conversation(conversation_id, user, session, title)

                # Store user message
                self._store_message_to_db(
                    conversation_id=conversation_id,
                    message_type="user",
                    content=message,
                    session=session
                )

                # Store AI response
                servers_used = [result.get("server_name") for result in tool_results]
                self._store_message_to_db(
                    conversation_id=conversation_id,
                    message_type="assistant",
                    content=llm_response,
                    session=session,
                    tool_calls=tool_results,
                    servers_used=servers_used,
                    extra_metadata={
                        "tool_analysis": tool_analysis,
                        "connected_servers_count": len(connected_servers)
                    }
                )

                # Also store in memory for backwards compatibility
                self._store_conversation_turn(
                    conversation_id, message, llm_response, tool_results
                )

            return {
                "response": llm_response,
                "tool_calls": tool_results,
                "servers_used": [result.get("server_name") for result in tool_results],
                "conversation_id": conversation_id
            }

        except Exception as e:
            logger.error(f"Error processing chat message: {e}")

            # Store error message in database if we have a conversation
            error_message = f"I apologize, but I encountered an error processing your request: {str(e)}"
            if conversation_id:
                try:
                    # Create conversation if it doesn't exist
                    title = message[:50] + "..." if len(message) > 50 else message
                    self._get_or_create_conversation(conversation_id, user, session, title)

                    # Store user message if we haven't already
                    self._store_message_to_db(
                        conversation_id=conversation_id,
                        message_type="user",
                        content=message,
                        session=session
                    )

                    # Store error message
                    self._store_message_to_db(
                        conversation_id=conversation_id,
                        message_type="error",
                        content=error_message,
                        session=session,
                        extra_metadata={"error": str(e), "error_type": type(e).__name__}
                    )
                except Exception as db_error:
                    logger.error(f"Failed to store error message to database: {db_error}")

            return {
                "response": error_message,
                "tool_calls": [],
                "servers_used": [],
                "conversation_id": conversation_id,
                "error": str(e)
            }

    def _format_tools_for_analysis(self, connected_servers: list[dict]) -> list[dict]:
        """Format connected servers' tools for LLM analysis"""
        tools = []
        for server in connected_servers:
            for tool in server.get("tools", []):
                tools.append({
                    "name": tool["name"],
                    "description": tool["description"],
                    "server": server["name"],
                    "parameters": tool.get("parameters", {})
                })
        return tools

    async def _generate_llm_response_with_service(
        self,
        user: User,
        session: Session,
        message: str,
        tool_results: list[dict],
        connected_servers: list[dict],
        conversation_id: str | None = None
    ) -> str:
        """Generate LLM response using the LLM service"""

        # Prepare conversation context
        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(connected_servers, tool_results)
            },
            {
                "role": "user",
                "content": message
            }
        ]

        # Add tool results context if available
        if tool_results:
            tool_context = self._format_tool_results_for_llm(tool_results)
            tool_instruction = LLMPrompts.get_tool_results_instruction()
            messages.insert(-1, {
                "role": "assistant",
                "content": f"I have executed the following tools based on your request:\n\n{tool_context}\n\n{tool_instruction}"
            })

        try:
            # Generate response using LLM service
            result = await llm_service.generate_response(user, session, messages)

            if result["success"]:
                llm_response = result["content"]

                # Validate response to prevent hallucination
                if not LLMPrompts.validate_response_against_data(llm_response, tool_results):
                    logger.warning("LLM response contains suspected hallucinated data, using fallback")
                    return await self._generate_llm_response(
                        message, tool_results, connected_servers, conversation_id
                    )

                return llm_response
            else:
                # Fallback to rule-based response if LLM fails
                logger.warning(f"LLM generation failed: {result.get('error')}")
                return await self._generate_llm_response(
                    message, tool_results, connected_servers, conversation_id
                )

        except Exception as e:
            logger.error(f"LLM service error: {e}")
            # Fallback to rule-based tool analysis when LLM is unavailable
            logger.info("Attempting rule-based tool analysis as LLM fallback")
            fallback_tools = await self._analyze_for_tools_fallback(message, connected_servers)
            if fallback_tools:
                tool_results = await self._execute_tools(fallback_tools)

            return await self._generate_llm_response(
                message, tool_results, connected_servers, conversation_id
            )

    def _build_system_prompt(self, connected_servers: list[dict], tool_results: list[dict]) -> str:
        """Build system prompt for the LLM"""
        return LLMPrompts.get_system_prompt(connected_servers, tool_results)

    def _format_tool_results_for_llm(self, tool_results: list[dict]) -> str:
        """Format tool results for LLM context with ACTUAL data to prevent hallucination"""
        formatted_results = []
        labels = LLMPrompts.get_data_labels()

        for result in tool_results:
            tool_name = result.get("tool_name", "Unknown")
            server_name = result.get("server_name", "Unknown")
            success = result.get("success", False)

            if success:
                # Extract and include the ACTUAL data from the result
                tool_result = result.get("result", {})

                if tool_result.get("result", {}).get("content"):
                    content_text = tool_result["result"]["content"][0].get("text", "")
                    try:
                        data = json.loads(content_text)

                        # Include the ACTUAL DATA for the LLM to use
                        if tool_name == "auto_authenticate":
                            formatted_results.append(f"✅ {tool_name} ({server_name}): {labels['authentication_success']}")
                        elif "leads" in data:
                            leads = data["leads"]
                            formatted_results.append(f"✅ {tool_name} ({server_name}): Retrieved {len(leads)} leads")
                            formatted_results.append(f"{labels['leads_data']}\n{json.dumps(leads, indent=2)}")
                        else:
                            # Include raw data for other tool types
                            formatted_results.append(f"✅ {tool_name} ({server_name}): Data retrieved")
                            formatted_results.append(f"{labels['general_data']}\n{json.dumps(data, indent=2)}")
                    except json.JSONDecodeError:
                        # Include raw text if it's not JSON
                        formatted_results.append(f"✅ {tool_name} ({server_name}): Data retrieved")
                        formatted_results.append(f"{labels['general_data']}\n{content_text}")
                else:
                    formatted_results.append(f"✅ {tool_name} ({server_name}): {labels['no_data_returned']}")
            else:
                error_msg = result.get("result", {}).get("error", "Unknown error")
                formatted_results.append(f"❌ {tool_name} ({server_name}): {labels['error_prefix']} {error_msg}")

        return "\n".join(formatted_results)

    async def _prepare_tools_for_execution(
        self,
        llm_tools: list[dict],
        connected_servers: list[dict],
        user: User,
        session: Session
    ) -> list[dict]:
        """Convert LLM tool analysis format to execution format"""
        execution_tools = []

        for llm_tool in llm_tools:
            tool_name = llm_tool.get("name")
            parameters = llm_tool.get("parameters", {})

            # Find the server that has this tool
            server_info = None
            for server in connected_servers:
                for tool in server.get("tools", []):
                    if tool["name"] == tool_name:
                        server_info = server
                        break
                if server_info:
                    break

            if not server_info:
                logger.warning(f"Tool {tool_name} not found in any connected server")
                continue

            # Check if this tool requires authentication
            requires_auth = self._tool_requires_authentication(tool_name)

            # If authentication is required, add auto_authenticate first
            if requires_auth and not any(t.get("tool_name") == "auto_authenticate" and t.get("server_id") == server_info["id"] for t in execution_tools):
                execution_tools.append({
                    "server_id": server_info["id"],
                    "server_name": server_info["name"],
                    "tool_name": "auto_authenticate",
                    "description": "Authenticate with server",
                    "parameters": {},
                    "requires_auth_token": False
                })

            # Add the main tool
            execution_tools.append({
                "server_id": server_info["id"],
                "server_name": server_info["name"],
                "tool_name": tool_name,
                "description": llm_tool.get("description", ""),
                "parameters": parameters,
                "requires_auth_token": requires_auth
            })

        return execution_tools

    def _tool_requires_authentication(self, tool_name: str) -> bool:
        """Check if a tool requires authentication"""
        # List of tools that require authentication
        auth_required_tools = [
            "get_leads", "search_leads_simple", "get_my_assigned_leads",
            "search_leads_advanced", "get_sales_team", "get_lead_activity_history",
            "get_lead_call_summaries"
        ]
        return tool_name in auth_required_tools

    async def _get_user_connected_servers(self, user: User, session: Session) -> list[dict]:
        """Get list of user's connected MCP servers with their tools"""
        statement = select(MCPServer).where(
            MCPServer.owner_id == user.id,
            MCPServer.status == "connected"
        )
        servers = session.exec(statement).all()

        connected_servers = []
        for server in servers:
            tools_info = []
            if server.tools:
                for tool in server.tools:
                    tools_info.append({
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "parameters": tool.get("inputSchema", {}).get("properties", {})
                    })

            connected_servers.append({
                "id": str(server.id),
                "name": server.name,
                "description": server.description,
                "tools": tools_info
            })

        return connected_servers

    async def _analyze_message_for_tools(self, message: str, servers: list[dict]) -> dict:
        """
        Analyze user message to determine if MCP tools are needed

        This is a simplified version - in production you'd use an LLM for this analysis
        """
        message_lower = message.lower()

        # Get keywords from prompts configuration
        patterns = LLMPrompts.get_fallback_patterns()
        crm_keywords = (patterns["general_crm"] + patterns["crm_search"] +
                       patterns["crm_recent"] + patterns["crm_assigned"])

        # Check if message contains CRM-related keywords
        needs_crm = any(keyword in message_lower for keyword in crm_keywords)

        required_tools = []

        if needs_crm:
            # Find CRM server
            crm_server = None
            for server in servers:
                if "crm" in server["name"].lower() or "scaler" in server["name"].lower():
                    crm_server = server
                    break

            if crm_server:
                # Determine which CRM tools might be needed
                if any(word in message_lower for word in ["lead", "leads", "recent", "latest", "list"]):
                    required_tools.append({
                        "server_id": crm_server["id"],
                        "server_name": crm_server["name"],
                        "tool_name": "auto_authenticate",
                        "description": "Authenticate with CRM",
                        "parameters": {}
                    })

                    # Determine specific lead operation
                    if any(word in message_lower for word in ["search", "find"]):
                        # Check if there's a search term
                        search_terms = self._extract_search_terms(message)
                        if search_terms:
                            required_tools.append({
                                "server_id": crm_server["id"],
                                "server_name": crm_server["name"],
                                "tool_name": "search_leads_simple",
                                "description": "Search for leads",
                                "parameters": {"query": search_terms},
                                "requires_auth_token": True
                            })
                        else:
                            required_tools.append({
                                "server_id": crm_server["id"],
                                "server_name": crm_server["name"],
                                "tool_name": "get_leads",
                                "description": "Get recent leads",
                                "parameters": {"limit": self._extract_number(message, default=5)},
                                "requires_auth_token": True
                            })
                    elif "assigned" in message_lower or "my" in message_lower:
                        required_tools.append({
                            "server_id": crm_server["id"],
                            "server_name": crm_server["name"],
                            "tool_name": "get_my_assigned_leads",
                            "description": "Get my assigned leads",
                            "parameters": {"limit": self._extract_number(message, default=5)},
                            "requires_auth_token": True
                        })
                    else:
                        required_tools.append({
                            "server_id": crm_server["id"],
                            "server_name": crm_server["name"],
                            "tool_name": "get_leads",
                            "description": "Get recent leads",
                            "parameters": {"limit": self._extract_number(message, default=5)},
                            "requires_auth_token": True
                        })

        return {
            "requires_tools": len(required_tools) > 0,
            "tools": required_tools,
            "analysis": {
                "needs_crm": needs_crm,
                "detected_keywords": [kw for kw in crm_keywords if kw in message_lower]
            }
        }

    def _extract_search_terms(self, message: str) -> str | None:
        """Extract search terms from message"""
        # Simple extraction - look for quoted terms or terms after "for"
        import re

        # Look for quoted terms
        quoted = re.search(r'"([^"]*)"', message)
        if quoted:
            return quoted.group(1)

        # Look for terms after "for", "named", "with"
        patterns = [
            r'(?:for|named|with)\s+([a-zA-Z0-9@._-]+)',
            r'email\s+([a-zA-Z0-9@._-]+)',
            r'called\s+([a-zA-Z0-9\s]+?)(?:\s|$)'
        ]

        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

    def _extract_number(self, message: str, default: int = 5) -> int:
        """Extract a number from message (for limits, etc.)"""
        import re

        # Look for numbers in the message
        numbers = re.findall(r'\b(\d+)\b', message)
        if numbers:
            # Return the first reasonable number (1-100)
            for num_str in numbers:
                num = int(num_str)
                if 1 <= num <= 100:
                    return num

        return default

    async def _execute_required_tools(
        self,
        tools: list[dict],
        user: User,
        session: Session
    ) -> list[dict]:
        """Execute the required MCP tools"""
        results = []
        auth_tokens = {}  # Store auth tokens by server

        for tool_spec in tools:
            try:
                server_id = tool_spec["server_id"]
                tool_name = tool_spec["tool_name"]
                parameters = tool_spec.get("arguments", tool_spec.get("parameters", {}))

                # If tool requires auth token, use stored token or get from previous auth
                if tool_spec.get("requires_auth_token") and server_id in auth_tokens:
                    parameters["token"] = auth_tokens[server_id]

                # Execute tool
                result = await mcp_manager.call_tool(
                    server_id, tool_name, parameters
                )

                # Store auth token if this was an authentication call
                if tool_name == "auto_authenticate" and result.get("success"):
                    try:
                        # Parse the authentication response to extract token
                        auth_response = result.get("result", {})
                        if auth_response.get("content"):
                            content_text = auth_response["content"][0].get("text", "")
                            auth_data = json.loads(content_text)
                            if auth_data.get("token"):
                                auth_tokens[server_id] = auth_data["token"]
                    except Exception as e:
                        logger.warning(f"Failed to extract auth token: {e}")

                results.append({
                    "server_id": server_id,
                    "server_name": tool_spec["server_name"],
                    "tool_name": tool_name,
                    "parameters": parameters,
                    "result": result,
                    "success": result.get("success", False)
                })

            except Exception as e:
                logger.error(f"Error executing tool {tool_name}: {e}")
                results.append({
                    "server_id": tool_spec["server_id"],
                    "server_name": tool_spec["server_name"],
                    "tool_name": tool_name,
                    "parameters": parameters,
                    "result": {"error": str(e)},
                    "success": False
                })

        return results

    async def _analyze_for_tools_fallback(self, message: str, connected_servers: list[dict]) -> list[dict]:
        """
        Fallback tool analysis when LLM is unavailable.
        Uses rule-based pattern matching to identify tool calls.
        """
        tools_to_execute = []
        message_lower = message.lower()

        # Find CRM servers
        crm_servers = [s for s in connected_servers if 'crm' in s.get('name', '').lower()]
        if not crm_servers:
            return tools_to_execute

        crm_server = crm_servers[0]  # Use first CRM server
        server_id = crm_server['id']

        # Add auto-authentication first
        tools_to_execute.append({
            "server_id": server_id,
            "tool_name": "auto_authenticate",
            "arguments": {}
        })

        # Get patterns from prompts
        patterns = LLMPrompts.get_fallback_patterns()

        # Search patterns
        if any(word in message_lower for word in patterns["crm_search"]):
            # Determine search type
            if 'gmail' in message_lower or '@gmail.com' in message_lower:
                # Search for Gmail leads
                tools_to_execute.append({
                    "server_id": server_id,
                    "tool_name": "search_leads_simple",
                    "arguments": {
                        "query": "gmail",
                        "limit": 10
                    },
                    "requires_auth_token": True
                })
            elif 'email' in message_lower and ('@' in message or 'com' in message_lower):
                # Extract email domain or search term
                email_terms = patterns["email_domains"]
                for term in email_terms:
                    if term in message_lower:
                        tools_to_execute.append({
                            "server_id": server_id,
                            "tool_name": "search_leads_simple",
                            "arguments": {
                                "query": term,
                                "limit": 10
                            },
                            "requires_auth_token": True
                        })
                        break
            else:
                # General lead search - get recent leads
                tools_to_execute.append({
                    "server_id": server_id,
                    "tool_name": "get_leads",
                    "arguments": {
                        "limit": 10,
                        "sort_field": "CreatedOn",
                        "sort_order": "desc"
                    },
                    "requires_auth_token": True
                })

        # Recent/latest leads
        elif any(word in message_lower for word in patterns["crm_recent"]):
            tools_to_execute.append({
                "server_id": server_id,
                "tool_name": "get_leads",
                "arguments": {
                    "limit": 10,
                    "sort_field": "CreatedOn",
                    "sort_order": "desc"
                },
                "requires_auth_token": True
            })

        # My leads
        elif any(word in message_lower for word in patterns["crm_assigned"]):
            tools_to_execute.append({
                "server_id": server_id,
                "tool_name": "get_my_assigned_leads",
                "arguments": {
                    "limit": 10
                },
                "requires_auth_token": True
            })

        return tools_to_execute

    async def _generate_llm_response(
        self,
        message: str,
        tool_results: list[dict],
        connected_servers: list[dict],
        conversation_id: str | None = None
    ) -> str:
        """
        Generate LLM response based on message and tool results

        For now, this is a rule-based response. In production, you'd use
        OpenAI GPT, Claude, or another LLM API.
        """

        if not tool_results:
            # No tools were called - provide general response
            error_messages = LLMPrompts.get_error_messages()
            if any(keyword in message.lower() for keyword in ["lead", "crm", "customer"]):
                if not connected_servers:
                    return error_messages["no_servers"]
                else:
                    return error_messages["be_more_specific"]
            else:
                return error_messages["generic_help"]

        # Process tool results and generate response
        response_parts = []

        for result in tool_results:
            if not result["success"]:
                response_parts.append(f"❌ Failed to execute {result['tool_name']}: {result['result'].get('error', 'Unknown error')}")
                continue

            tool_name = result["tool_name"]
            tool_result = result["result"]

            if tool_name == "auto_authenticate":
                response_parts.append("✅ Successfully authenticated with CRM")

            elif tool_name in ["get_leads", "search_leads_simple", "get_my_assigned_leads"]:
                leads_data = self._extract_leads_from_result(tool_result)
                if leads_data:
                    response_parts.append(self._format_leads_response(leads_data, tool_name))
                else:
                    response_parts.append("No leads found matching your criteria.")

        if response_parts:
            return "\n\n".join(response_parts)
        else:
            return "I executed the requested operations, but didn't find any data to display."

    def _extract_leads_from_result(self, tool_result: dict) -> list[dict] | None:
        """Extract leads data from tool result"""
        try:
            if tool_result.get("result", {}).get("content"):
                content_text = tool_result["result"]["content"][0].get("text", "")
                data = json.loads(content_text)
                return data.get("leads", [])
        except Exception as e:
            logger.warning(f"Failed to extract leads from result: {e}")
        return None

    def _format_leads_response(self, leads: list[dict], tool_name: str) -> str:
        """Format leads data for chat response"""
        if not leads:
            return "No leads found."

        action_map = {
            "get_leads": "Here are the most recent leads",
            "search_leads_simple": "Here are the search results",
            "get_my_assigned_leads": "Here are your assigned leads"
        }

        header = action_map.get(tool_name, "Here are the leads")

        formatted_leads = []
        for i, lead in enumerate(leads[:10], 1):  # Limit to 10 leads
            name = lead.get("fullName", "Unknown")
            email = lead.get("email", "No email")
            phone = None
            engagement_score = None

            # Extract phone and engagement score from attributes
            for attr in lead.get("combinedLeadAttributeValues", []):
                if attr.get("schemaName") == "Phone":
                    phone = attr.get("value")
                elif attr.get("schemaName") == "EngagementScore":
                    engagement_score = attr.get("value")

            lead_info = f"{i}. **{name}**\n   📧 {email}"
            if phone:
                lead_info += f"\n   📞 {phone}"
            if engagement_score:
                lead_info += f"\n   📊 Engagement: {engagement_score}"

            formatted_leads.append(lead_info)

        total_count = len(leads)
        response = f"{header} ({total_count} found):\n\n" + "\n\n".join(formatted_leads)

        if len(leads) > 10:
            response += f"\n\n... and {len(leads) - 10} more leads. Ask for specific criteria to narrow down results."

        return response

    def _store_conversation_turn(
        self,
        conversation_id: str,
        user_message: str,
        ai_response: str,
        tool_results: list[dict]
    ):
        """Store conversation turn in memory (in production, use database)"""
        if conversation_id not in self.conversation_history:
            self.conversation_history[conversation_id] = []

        self.conversation_history[conversation_id].append({
            "user_message": user_message,
            "ai_response": ai_response,
            "tool_results": tool_results,
            "timestamp": "2025-01-06T00:00:00Z"  # In production, use actual timestamp
        })

        # Keep only last 20 turns to prevent memory bloat
        if len(self.conversation_history[conversation_id]) > 20:
            self.conversation_history[conversation_id] = self.conversation_history[conversation_id][-20:]

    def _get_or_create_conversation(
        self,
        conversation_id: str,
        user: User,
        session: Session,
        title: str | None = None
    ) -> ChatConversation:
        """Get existing conversation or create a new one"""
        # Try to get existing conversation
        statement = select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.owner_id == user.id
        )
        conversation = session.exec(statement).first()

        if not conversation:
            # Create new conversation
            conversation = ChatConversation(
                id=conversation_id,
                title=title,
                owner_id=user.id
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            logger.info(f"Created new conversation: {conversation_id}")

        return conversation

    def _store_message_to_db(
        self,
        conversation_id: str,
        message_type: str,
        content: str,
        session: Session,
        tool_calls: list[dict] | None = None,
        servers_used: list[str] | None = None,
        extra_metadata: dict | None = None
    ) -> ChatMessageDB:
        """Store a message to the database"""
        try:
            message = ChatMessageDB(
                conversation_id=conversation_id,
                message_type=message_type,
                content=content,
                tool_calls=tool_calls,
                servers_used=servers_used,
                extra_metadata=extra_metadata or {}
            )
            session.add(message)
            session.commit()
            session.refresh(message)

            # Update conversation message count and timestamp
            conversation = session.get(ChatConversation, conversation_id)
            if conversation:
                conversation.message_count += 1
                conversation.updated_at = datetime.utcnow().isoformat()
                session.add(conversation)
                session.commit()

            logger.debug(f"Stored {message_type} message to conversation {conversation_id}")
            return message

        except Exception as e:
            logger.error(f"Failed to store message to database: {e}")
            session.rollback()
            raise

    def get_conversation_messages(
        self,
        conversation_id: str,
        user: User,
        session: Session,
        limit: int = 100,
        offset: int = 0
    ) -> list[ChatMessageDB]:
        """Get messages from a conversation"""
        # Verify user owns the conversation
        conversation_statement = select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.owner_id == user.id
        )
        conversation = session.exec(conversation_statement).first()

        if not conversation:
            return []

        # Get messages
        messages_statement = (
            select(ChatMessageDB)
            .where(ChatMessageDB.conversation_id == conversation_id)
            .order_by(ChatMessageDB.timestamp)
            .offset(offset)
            .limit(limit)
        )

        return list(session.exec(messages_statement).all())

    def get_user_conversations(
        self,
        user: User,
        session: Session,
        limit: int = 50,
        offset: int = 0
    ) -> list[ChatConversation]:
        """Get all conversations for a user"""
        statement = (
            select(ChatConversation)
            .where(ChatConversation.owner_id == user.id)
            .order_by(ChatConversation.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return list(session.exec(statement).all())

    def delete_conversation(
        self,
        conversation_id: str,
        user: User,
        session: Session
    ) -> bool:
        """Delete a conversation and all its messages"""
        try:
            # Verify user owns the conversation
            conversation = session.get(ChatConversation, conversation_id)
            if not conversation or conversation.owner_id != user.id:
                return False

            # Delete conversation (messages will be deleted via CASCADE)
            session.delete(conversation)
            session.commit()

            logger.info(f"Deleted conversation {conversation_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete conversation {conversation_id}: {e}")
            session.rollback()
            return False


# Global chat service instance
chat_service = ChatService()
