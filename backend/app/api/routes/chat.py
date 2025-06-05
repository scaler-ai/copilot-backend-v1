import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    ChatMessage, 
    ChatResponse, 
    ChatToolCall, 
    ChatConversationsPublic,
    ChatMessagesPublic,
    ChatConversationPublic,
    ChatMessagePublic
)
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


@router.get("/history/{conversation_id}", response_model=ChatMessagesPublic)
async def get_chat_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: str,
    limit: int = 100,
    offset: int = 0
) -> Any:
    """
    Get chat conversation history from database.
    """
    try:
        # Get conversation messages from database
        messages = chat_service.get_conversation_messages(
            conversation_id=conversation_id,
            user=current_user,
            session=session,
            limit=limit,
            offset=offset
        )
        
        # Convert to public models
        message_data = [
            ChatMessagePublic(
                id=msg.id,
                conversation_id=msg.conversation_id,
                message_type=msg.message_type,
                content=msg.content,
                timestamp=msg.timestamp,
                tool_calls=msg.tool_calls,
                servers_used=msg.servers_used,
                extra_metadata=msg.extra_metadata
            )
            for msg in messages
        ]
        
        return ChatMessagesPublic(data=message_data, count=len(message_data))
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get chat history: {str(e)}")


@router.delete("/history/{conversation_id}")
async def clear_chat_history(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: str
) -> Any:
    """
    Delete a chat conversation and all its messages.
    """
    try:
        # Delete conversation from database
        success = chat_service.delete_conversation(
            conversation_id=conversation_id,
            user=current_user,
            session=session
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Conversation not found or not owned by user")
        
        # Also clear from memory
        if conversation_id in chat_service.conversation_history:
            del chat_service.conversation_history[conversation_id]
        
        return {"message": f"Chat conversation {conversation_id} deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete chat conversation: {str(e)}")


@router.get("/conversations", response_model=ChatConversationsPublic)
async def list_conversations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = 50,
    offset: int = 0
) -> Any:
    """
    List all chat conversations for the user from database.
    """
    try:
        # Get conversations from database
        conversations = chat_service.get_user_conversations(
            user=current_user,
            session=session,
            limit=limit,
            offset=offset
        )
        
        # Convert to public models
        conversation_data = [
            ChatConversationPublic(
                id=conv.id,
                title=conv.title,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=conv.message_count,
                owner_id=conv.owner_id
            )
            for conv in conversations
        ]
        
        return ChatConversationsPublic(data=conversation_data, count=len(conversation_data))
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list conversations: {str(e)}")