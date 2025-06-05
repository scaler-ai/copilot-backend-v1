"""
LLM prompts and instructions for the chat system.

This file contains system prompts and instructions that are used to guide the LLM
in generating appropriate responses. Separating them here makes it easy to modify
and experiment with different prompts without changing the service logic.
"""

from typing import Dict, List


class LLMPrompts:
    """Container for LLM prompts and instructions"""
    
    @staticmethod
    def get_system_prompt(connected_servers: List[Dict], tool_results: List[Dict]) -> str:
        """
        Build system prompt for the LLM based on available servers and tool results.
        
        Args:
            connected_servers: List of user's connected MCP servers
            tool_results: Results from any tool executions
            
        Returns:
            Complete system prompt string
        """
        base_prompt = """You are an intelligent AI assistant that helps users interact with their connected MCP (Model Context Protocol) servers. You can access various tools and data sources to provide helpful responses.

Your capabilities:
- Analyze user requests and determine when to use specific tools
- Execute tools through MCP servers to retrieve data
- Provide clear, helpful responses based on tool results
- Handle CRM operations, lead management, and other business workflows

Guidelines:
- Be conversational and helpful
- When tool results are available, integrate them naturally into your response
- Format data clearly (use bullet points, numbers, etc.)
- If no tools were needed, provide general assistance
- Always be honest about what you can and cannot do"""
        
        # Add server information
        if connected_servers:
            base_prompt += f"\n\nConnected MCP Servers ({len(connected_servers)}):\n"
            for server in connected_servers:
                base_prompt += f"- {server['name']}: {server.get('description', 'No description')}\n"
                if server.get('tools'):
                    base_prompt += f"  Available tools: {len(server['tools'])}\n"
        
        # Add tool execution context
        if tool_results:
            base_prompt += f"\n\nTool execution results are available and should be used to provide a comprehensive response."
        
        return base_prompt
    
    @staticmethod
    def get_tool_analysis_prompt(message: str, available_tools: List[Dict]) -> str:
        """
        Build prompt for LLM to analyze if tools are needed for a user message.
        
        Args:
            message: User's message
            available_tools: List of available tools from connected servers
            
        Returns:
            Prompt for tool analysis
        """
        return f"""Analyze the following user message and determine if any MCP tools should be called to fulfill the request.

User message: "{message}"

Available tools:
{LLMPrompts._format_tools_list(available_tools)}

Instructions:
1. Determine if the user's request requires calling any of the available tools
2. If tools are needed, specify which tools and what parameters to use
3. Consider authentication requirements (some tools may need auto_authenticate first)
4. Respond with JSON in this format:

For requests that require tools:
{{
    "requires_tools": true,
    "tools": [
        {{
            "name": "tool_name",
            "description": "what this tool does",
            "parameters": {{"param1": "value1", "param2": "value2"}}
        }}
    ],
    "reasoning": "explanation of why these tools are needed"
}}

For requests that don't require tools:
{{
    "requires_tools": false,
    "reasoning": "explanation of why no tools are needed"
}}

Focus on the user's intent and choose the most appropriate tools to fulfill their request."""

    @staticmethod
    def get_response_generation_prompt(
        message: str, 
        tool_results: List[Dict], 
        connected_servers: List[Dict]
    ) -> str:
        """
        Build prompt for generating the final response to the user.
        
        Args:
            message: Original user message
            tool_results: Results from tool executions
            connected_servers: Available MCP servers
            
        Returns:
            Prompt for response generation
        """
        prompt = f"""Generate a helpful response to the user's message based on the tool execution results.

User's original message: "{message}"

Connected servers: {len(connected_servers)} MCP servers available"""
        
        if tool_results:
            prompt += f"\n\nTool execution results:\n"
            for i, result in enumerate(tool_results, 1):
                success = "✅" if result.get("success") else "❌"
                tool_name = result.get("tool_name", "Unknown")
                server_name = result.get("server_name", "Unknown")
                prompt += f"{i}. {success} {tool_name} ({server_name})\n"
                
                if result.get("success") and result.get("result"):
                    # Add summary of successful results
                    prompt += f"   Result: {str(result['result'])[:200]}...\n"
                elif not result.get("success"):
                    error = result.get("result", {}).get("error", "Unknown error")
                    prompt += f"   Error: {error}\n"
        
        prompt += """

Instructions:
1. Provide a clear, conversational response that addresses the user's request
2. If tool results contain data, format it nicely (use bullet points, numbers, etc.)
3. If there were errors, acknowledge them and suggest alternatives
4. Be helpful and specific based on the actual results
5. Don't mention technical details about MCP or tool execution unless relevant
6. Keep the response focused and concise while being comprehensive

Generate your response now:"""
        
        return prompt

    @staticmethod
    def _format_tools_list(tools: List[Dict]) -> str:
        """Format list of tools for prompts"""
        if not tools:
            return "No tools available"
        
        formatted = []
        for tool in tools:
            name = tool.get("name", "Unknown")
            description = tool.get("description", "No description")
            server = tool.get("server", "Unknown")
            formatted.append(f"- {name} ({server}): {description}")
        
        return "\n".join(formatted)

    @staticmethod
    def get_fallback_patterns() -> Dict[str, List[str]]:
        """
        Get pattern matching rules for fallback tool selection when LLM is unavailable.
        
        Returns:
            Dictionary mapping intent types to keyword patterns
        """
        return {
            "crm_search": [
                "search", "find", "look for", "get leads", "leads with", "search for leads"
            ],
            "crm_recent": [
                "recent", "latest", "new", "show me leads", "list leads"
            ],
            "crm_assigned": [
                "my leads", "assigned to me", "my assigned leads"
            ],
            "email_domains": [
                "gmail", "yahoo", "hotmail", "outlook", "@gmail.com", "@yahoo.com"
            ],
            "general_crm": [
                "lead", "leads", "crm", "customer", "customers", "contact", "contacts",
                "prospect", "prospects", "sales", "pipeline"
            ]
        }

    @staticmethod
    def get_error_messages() -> Dict[str, str]:
        """
        Get standardized error messages for different scenarios.
        
        Returns:
            Dictionary of error message templates
        """
        return {
            "no_servers": "I'd be happy to help with CRM operations, but you don't have any MCP servers connected. Please connect to your CRM server first.",
            "llm_unavailable": "I'm having trouble analyzing your request right now, but I'll try to help based on common patterns.",
            "tool_execution_failed": "I encountered an error while executing the requested operation: {error}",
            "no_crm_server": "I can help with CRM operations, but I don't see any CRM servers connected to your account.",
            "generic_help": "I can help you interact with your connected MCP servers. I can access CRM data, search for leads, and perform various operations. What would you like to do?",
            "be_more_specific": "I can help you with CRM operations. Please be more specific about what you'd like to do (e.g., 'show me recent leads', 'search for leads with gmail')."
        }