import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.models import ChatMessage, ChatResponse, ChatToolCall
from app.services.chat_service import chat_service

router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def chat_with_llm(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    chat_message: ChatMessage
) -> Any:
    """
    Send a chat message and receive LLM response with automatic MCP tool calling.
    """
    try:
        # Generate conversation ID if not provided
        conversation_id = chat_message.conversation_id
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        
        # Process the chat message
        result = await chat_service.process_chat_message(
            user=current_user,
            message=chat_message.message,
            session=session,
            conversation_id=conversation_id
        )
        
        # Convert tool results to ChatToolCall models
        tool_calls = []
        for tool_result in result.get("tool_calls", []):
            tool_calls.append(ChatToolCall(
                server_id=tool_result["server_id"],
                server_name=tool_result["server_name"],
                tool_name=tool_result["tool_name"],
                parameters=tool_result["parameters"],
                result=tool_result["result"],
                success=tool_result["success"]
            ))
        
        return ChatResponse(
            response=result["response"],
            tool_calls=tool_calls,
            servers_used=result["servers_used"],
            conversation_id=result["conversation_id"],
            error=result.get("error")
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")


@router.get("/history/{conversation_id}")
async def get_chat_history(
    *,
    current_user: CurrentUser,
    conversation_id: str
) -> Any:
    """
    Get chat conversation history.
    """
    try:
        # Get conversation history from chat service
        history = chat_service.conversation_history.get(conversation_id, [])
        
        return {
            "conversation_id": conversation_id,
            "history": history,
            "total_turns": len(history)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chat history: {str(e)}")


@router.delete("/history/{conversation_id}")
async def clear_chat_history(
    *,
    current_user: CurrentUser,
    conversation_id: str
) -> Any:
    """
    Clear chat conversation history.
    """
    try:
        # Clear conversation history
        if conversation_id in chat_service.conversation_history:
            del chat_service.conversation_history[conversation_id]
        
        return {"message": f"Chat history cleared for conversation {conversation_id}"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear chat history: {str(e)}")


@router.get("/conversations")
async def list_conversations(
    *,
    current_user: CurrentUser
) -> Any:
    """
    List all active chat conversations for the user.
    Note: This is a simple in-memory implementation.
    In production, you'd store conversations in the database with user association.
    """
    try:
        conversations = []
        for conv_id, history in chat_service.conversation_history.items():
            if history:  # Only include conversations with messages
                last_turn = history[-1]
                conversations.append({
                    "conversation_id": conv_id,
                    "last_message": last_turn.get("user_message", "")[:100],
                    "last_response": last_turn.get("ai_response", "")[:100],
                    "turn_count": len(history),
                    "timestamp": last_turn.get("timestamp")
                })
        
        # Sort by most recent
        conversations.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        
        return {
            "conversations": conversations,
            "total": len(conversations)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list conversations: {str(e)}")