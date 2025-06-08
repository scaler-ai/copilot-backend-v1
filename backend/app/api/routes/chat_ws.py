"""
Production-ready WebSocket endpoint for real-time chat streaming
"""
import json
import logging
import uuid
from typing import Any

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app.api.deps import get_db
from app.core.config import settings
from app.models import User
from app.services.chat_service import chat_service

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatWebSocketManager:
    """Manages WebSocket connections for real-time chat streaming"""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.user_sessions: dict[str, dict] = {}  # user_id -> session info

    async def connect(self, websocket: WebSocket, user_id: str):
        """Register WebSocket connection"""
        self.active_connections[user_id] = websocket
        self.user_sessions[user_id] = {
            "current_conversation": None,
            "streaming": False
        }
        logger.info(f"Chat WebSocket connected for user {user_id}")

    def disconnect(self, user_id: str):
        """Handle WebSocket disconnection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]
        logger.info(f"Chat WebSocket disconnected for user {user_id}")

    async def send_message(self, user_id: str, message: dict):
        """Send message to specific user with error handling"""
        websocket = self.active_connections.get(user_id)
        if websocket:
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.warning(f"Failed to send message to user {user_id}: {e}")
                self.disconnect(user_id)
                return False
        return True

    async def stream_response_chunk(self, user_id: str, chunk: str, conversation_id: str, message_id: str):
        """Stream a response chunk to the user"""
        return await self.send_message(user_id, {
            "type": "response_chunk",
            "conversation_id": conversation_id,
            "message_id": message_id,
            "chunk": chunk
        })

    async def send_response_complete(self, user_id: str, conversation_id: str, message_id: str,
                                   full_response: str, tool_calls: list = None):
        """Signal that response streaming is complete"""
        return await self.send_message(user_id, {
            "type": "response_complete",
            "conversation_id": conversation_id,
            "message_id": message_id,
            "full_response": full_response,
            "tool_calls": tool_calls or []
        })

    async def send_tool_execution_start(self, user_id: str, conversation_id: str, tool_name: str, server_name: str):
        """Notify about tool execution start"""
        return await self.send_message(user_id, {
            "type": "tool_execution_start",
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "server_name": server_name
        })

    async def send_tool_execution_complete(self, user_id: str, conversation_id: str,
                                         tool_name: str, success: bool, result: Any = None):
        """Notify about tool execution completion"""
        return await self.send_message(user_id, {
            "type": "tool_execution_complete",
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "success": success,
            "result": result
        })

    async def send_error(self, user_id: str, error_message: str, conversation_id: str = None):
        """Send error message to user"""
        return await self.send_message(user_id, {
            "type": "error",
            "conversation_id": conversation_id,
            "message": error_message
        })


# Global WebSocket manager instance
chat_ws_manager = ChatWebSocketManager()


@router.websocket("/ws")
async def chat_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat streaming

    Supports:
    - Word-by-word response streaming
    - Real-time tool execution notifications
    - Conversation management
    - Error handling
    """
    logger.info(f"Chat WebSocket endpoint called - URL: {websocket.url}")
    session: Session | None = None
    user: User | None = None
    user_id: str | None = None

    try:
        # Accept connection first (required by FastAPI WebSocket)
        await websocket.accept()
        logger.info("Chat WebSocket connection accepted")
        
        # Validate origin for CORS compliance after accepting
        origin = websocket.headers.get("origin")
        if origin and origin not in settings.all_cors_origins:
            logger.warning(f"Chat WebSocket connection rejected: Invalid origin {origin}")
            await websocket.close(code=1008, reason="Invalid origin")
            return
        
        logger.info(f"Chat WebSocket connection from origin: {origin}")

        # Get token from query parameters
        token = websocket.query_params.get("token")
        if not token:
            logger.warning("Chat WebSocket connection rejected: No token provided")
            await websocket.close(code=1008, reason="No authentication token")
            return

        # Validate token
        try:
            from app.core.security import ALGORITHM
            from app.models import TokenPayload
            
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
            token_data = TokenPayload(**payload)
            if not token_data.sub:
                await websocket.close(code=1008, reason="Invalid token")
                return

            # Get user from database
            session = next(get_db())
            user = session.get(User, token_data.sub)
            if not user:
                await websocket.close(code=1008, reason="User not found")
                return
            
            if not user.is_active:
                await websocket.close(code=1008, reason="Inactive user")
                return

        except jwt.ExpiredSignatureError:
            logger.warning("Chat WebSocket connection rejected: Expired token")
            await websocket.close(code=1008, reason="Token expired")
            return
        except Exception as e:
            logger.error(f"Chat WebSocket authentication failed: {e}")
            await websocket.close(code=1008, reason="Authentication failed")
            return

        # Set up connection in manager
        await chat_ws_manager.connect(websocket, str(user.id))

        # Send initial connection success message
        await websocket.send_text(json.dumps({
            "type": "connection",
            "status": "connected",
            "message": "Chat WebSocket connected successfully",
            "user_id": str(user.id)
        }))

        # Handle incoming messages
        while True:
            try:
                # Receive message
                data = await websocket.receive_text()
                message_data = json.loads(data)

                logger.debug(f"Chat WebSocket received from user {user.id}: {message_data}")

                # Handle different message types
                msg_type = message_data.get("type")

                if msg_type == "ping":
                    # Respond to ping
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "timestamp": message_data.get("timestamp")
                    }))

                elif msg_type == "chat_message":
                    # Process chat message with streaming
                    await handle_chat_message(
                        user, session, message_data, chat_ws_manager
                    )

                elif msg_type == "stop_generation":
                    # Stop current response generation
                    chat_ws_manager.user_sessions[str(user.id)]["streaming"] = False
                    await websocket.send_text(json.dumps({
                        "type": "generation_stopped",
                        "conversation_id": message_data.get("conversation_id")
                    }))

                else:
                    # Unknown message type
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}"
                    }))

            except WebSocketDisconnect:
                logger.info(f"Chat WebSocket disconnected for user {user.id}")
                break
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from user {user.id}: {e}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))
            except Exception as e:
                logger.error(f"Chat WebSocket error for user {user.id}: {e}")
                await chat_ws_manager.send_error(str(user.id), str(e))

    except Exception as e:
        logger.error(f"Chat WebSocket connection error: {e}")
    finally:
        # Clean up
        if user_id:
            chat_ws_manager.disconnect(user_id)
        if session:
            session.close()


async def handle_chat_message(
    user: User,
    session: Session,
    message_data: dict,
    ws_manager: ChatWebSocketManager
):
    """Handle incoming chat message with streaming response"""
    try:
        message = message_data.get("message", "")
        conversation_id = message_data.get("conversation_id")

        if not message.strip():
            await ws_manager.send_error(str(user.id), "Message cannot be empty")
            return

        # Generate conversation ID if not provided
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Generate unique message ID for this response
        message_id = str(uuid.uuid4())

        # Set streaming flag
        ws_manager.user_sessions[str(user.id)]["streaming"] = True
        ws_manager.user_sessions[str(user.id)]["current_conversation"] = conversation_id

        # Send message received acknowledgment
        await ws_manager.send_message(str(user.id), {
            "type": "message_received",
            "conversation_id": conversation_id,
            "message_id": message_id
        })

        # Process the chat message with streaming
        await process_chat_message_streaming(
            user, message, session, conversation_id, message_id, ws_manager
        )

    except Exception as e:
        logger.error(f"Error handling chat message: {e}")
        await ws_manager.send_error(str(user.id), f"Failed to process message: {str(e)}")
    finally:
        # Clear streaming flag
        if str(user.id) in ws_manager.user_sessions:
            ws_manager.user_sessions[str(user.id)]["streaming"] = False


async def process_chat_message_streaming(
    user: User,
    message: str,
    session: Session,
    conversation_id: str,
    message_id: str,
    ws_manager: ChatWebSocketManager
):
    """Process chat message with real-time streaming support"""
    try:
        # Use the existing chat service but with streaming modifications
        result = await chat_service.process_chat_message_streaming(
            user=user,
            message=message,
            session=session,
            conversation_id=conversation_id,
            message_id=message_id,
            ws_manager=ws_manager
        )

        # Send final completion message
        await ws_manager.send_response_complete(
            str(user.id),
            conversation_id,
            message_id,
            result["response"],
            result.get("tool_calls", [])
        )

    except Exception as e:
        logger.error(f"Error in streaming chat processing: {e}")
        await ws_manager.send_error(
            str(user.id),
            f"Chat processing failed: {str(e)}",
            conversation_id
        )


# Export the WebSocket manager for use in other modules
__all__ = ["router", "chat_ws_manager"]

