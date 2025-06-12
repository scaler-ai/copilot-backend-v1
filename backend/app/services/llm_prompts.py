"""
LLM prompts and instructions for the chat system.

This file contains system prompts and instructions that are used to guide the LLM
in generating appropriate responses. Separating them here makes it easy to modify
and experiment with different prompts without changing the service logic.
"""



class LLMPrompts:
    """Container for LLM prompts and instructions"""

    @staticmethod
    def get_system_prompt(connected_servers: list[dict], tool_results: list[dict]) -> str:
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

CRITICAL RULES - NEVER VIOLATE THESE:
- NEVER make up, invent, or hallucinate data
- ONLY use data that was actually returned by MCP tool calls
- If no real data is available, clearly state that no data was found
- If tool execution failed, report the actual error
- NEVER create fake names, emails, companies, or any other details
- Always base your response on actual tool results provided to you

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
            base_prompt += "\n\nTool execution results are available and should be used to provide a comprehensive response.\n\nREMINDER: You must ONLY use the actual data provided in the tool results. Do NOT create fake data, names, emails, or any other details. If the data is missing or insufficient, say so clearly."

        return base_prompt

    @staticmethod
    def get_tool_analysis_prompt(message: str, available_tools: list[dict]) -> str:
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
        tool_results: list[dict],
        connected_servers: list[dict]
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
            prompt += "\n\nTool execution results:\n"
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
    def _format_tools_list(tools: list[dict]) -> str:
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
    def get_fallback_patterns() -> dict[str, list[str]]:
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
    def get_tool_results_instruction() -> str:
        """
        Get the instruction to append when providing tool results to LLM.

        Returns:
            Instruction text for tool results context
        """
        return "IMPORTANT: Use ONLY the actual data shown above. Do NOT make up or invent any information."

    @staticmethod
    def get_data_labels() -> dict[str, str]:
        """
        Get standardized labels for formatting tool results data.

        Returns:
            Dictionary of data type labels
        """
        return {
            "leads_data": "ACTUAL LEAD DATA:",
            "general_data": "ACTUAL DATA:",
            "authentication_success": "Successfully authenticated",
            "no_data_returned": "Executed successfully (no data returned)",
            "error_prefix": "ERROR -"
        }

    @staticmethod
    def validate_response_against_data(response: str, tool_results: list[dict]) -> bool:
        """
        Validate that the response doesn't contain hallucinated data.

        Args:
            response: The LLM-generated response
            tool_results: The actual tool results that should be the source of truth

        Returns:
            True if response seems valid, False if it likely contains hallucinated data
        """
        # Common signs of hallucination
        suspicious_patterns = [
            "John Doe", "Jane Smith", "Robert Johnson", "Alice Williams", "Michael Brown",
            "ABC Corp", "XYZ LLC", "123 Industries", "789 Solutions", "DEF Inc",
            "@abccorp.com", "@xyzllc.com", "@123ind.com", "@789solutions.com", "@definc.com"
        ]

        # Check if response contains common fake data patterns
        response_lower = response.lower()
        for pattern in suspicious_patterns:
            if pattern.lower() in response_lower:
                return False

        # If we have tool results with actual data, ensure response references real data
        if tool_results:
            has_real_data = False
            for result in tool_results:
                if result.get("success") and result.get("result", {}).get("result", {}).get("content"):
                    has_real_data = True
                    break

            # If we have real data but response contains generic examples, flag as suspicious
            if has_real_data and any(pattern in response_lower for pattern in ["lead #1", "lead #2", "example.com"]):
                return False

        return True

    @staticmethod
    def get_error_messages() -> dict[str, str]:
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


# Sales Analysis Prompts
SALES_SKILL_ANALYSIS_PROMPT = """
Analyze the following sales activity data and infer skills:

Activities Summary:
- Total calls: {total_calls}
- Email interactions: {email_count}  
- Average response time: {avg_response_time}
- Lead engagement score: {engagement_score}
- Conversion rate: {conversion_rate}

Recent interactions:
{recent_activities}

Based on this data, assess the sales representative's skills in:
1. Communication effectiveness
2. Relationship building
3. Closing ability
4. Time management
5. Product knowledge

Provide a confidence score (1-5) for each skill.
"""

CONVERSATION_ANALYSIS_PROMPT = """
Analyze this sales conversation transcript and provide constructive feedback:

Transcript: {transcript_text}
Customer Profile: {customer_info}
Conversation Outcome: {outcome}

Please analyze:
1. What the sales rep did well (with specific examples)
2. Areas for improvement (with specific moments)
3. Missed opportunities (what could have been said/done)
4. Recommended techniques for similar situations
5. Specific phrases or approaches to try next time

Format the feedback to be:
- Specific and actionable
- Encouraging and constructive
- Based on actual conversation moments
- Focused on skill development
"""

SALES_FEEDBACK_GENERATION_PROMPT = """
Generate constructive feedback for a sales representative based on their performance:

Performance Metrics:
{performance_metrics}

Skill Assessment:
{skill_assessment}

Generate:
1. 3-5 key strengths with specific examples
2. 3-5 improvement areas with actionable suggestions
3. Personalized learning recommendations
4. Next steps for skill development

Keep feedback positive, specific, and actionable.
"""
