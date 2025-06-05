import json
import logging
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.models import MCPServer, User
from app.services.mcp_manager import mcp_manager


logger = logging.getLogger(__name__)


class ChatService:
    """Service for handling chat with LLM and MCP tool integration"""
    
    def __init__(self):
        self.conversation_history: Dict[str, List[Dict]] = {}
    
    async def process_chat_message(
        self, 
        user: User, 
        message: str, 
        session: Session,
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
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
            
            # Analyze message for potential tool calls
            tool_analysis = await self._analyze_message_for_tools(message, connected_servers)
            
            # Execute any identified tools
            tool_results = []
            if tool_analysis.get("requires_tools"):
                tool_results = await self._execute_required_tools(
                    tool_analysis["tools"], user, session
                )
            
            # Generate LLM response with context and tool results
            llm_response = await self._generate_llm_response(
                message, tool_results, connected_servers, conversation_id
            )
            
            # Store conversation history
            if conversation_id:
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
            return {
                "response": f"I apologize, but I encountered an error processing your request: {str(e)}",
                "tool_calls": [],
                "servers_used": [],
                "conversation_id": conversation_id,
                "error": str(e)
            }
    
    async def _get_user_connected_servers(self, user: User, session: Session) -> List[Dict]:
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
    
    async def _analyze_message_for_tools(self, message: str, servers: List[Dict]) -> Dict:
        """
        Analyze user message to determine if MCP tools are needed
        
        This is a simplified version - in production you'd use an LLM for this analysis
        """
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
    
    def _extract_search_terms(self, message: str) -> Optional[str]:
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
        tools: List[Dict], 
        user: User, 
        session: Session
    ) -> List[Dict]:
        """Execute the required MCP tools"""
        results = []
        auth_tokens = {}  # Store auth tokens by server
        
        for tool_spec in tools:
            try:
                server_id = tool_spec["server_id"]
                tool_name = tool_spec["tool_name"]
                parameters = tool_spec.get("parameters", {})
                
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
    
    async def _generate_llm_response(
        self, 
        message: str, 
        tool_results: List[Dict], 
        connected_servers: List[Dict],
        conversation_id: Optional[str] = None
    ) -> str:
        """
        Generate LLM response based on message and tool results
        
        For now, this is a rule-based response. In production, you'd use
        OpenAI GPT, Claude, or another LLM API.
        """
        
        if not tool_results:
            # No tools were called - provide general response
            if any(keyword in message.lower() for keyword in ["lead", "crm", "customer"]):
                if not connected_servers:
                    return "I'd be happy to help with CRM operations, but you don't have any MCP servers connected. Please connect to your CRM server first."
                else:
                    return "I can help you with CRM operations. Please be more specific about what you'd like to do (e.g., 'show me recent leads', 'search for leads with gmail')."
            else:
                return "Hello! I can help you interact with your connected MCP servers. I can access CRM data, search for leads, and perform various operations. What would you like to do?"
        
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
    
    def _extract_leads_from_result(self, tool_result: Dict) -> Optional[List[Dict]]:
        """Extract leads data from tool result"""
        try:
            if tool_result.get("result", {}).get("content"):
                content_text = tool_result["result"]["content"][0].get("text", "")
                data = json.loads(content_text)
                return data.get("leads", [])
        except Exception as e:
            logger.warning(f"Failed to extract leads from result: {e}")
        return None
    
    def _format_leads_response(self, leads: List[Dict], tool_name: str) -> str:
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
        tool_results: List[Dict]
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


# Global chat service instance
chat_service = ChatService()