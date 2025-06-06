"""
Production-ready WebSocket endpoint for MCP (Model Context Protocol) real-time communication
"""
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models import MCPServer, User
from app.services.mcp_manager import mcp_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class MCPWebSocketManager:
    """Manages WebSocket connections for MCP real-time updates"""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.user_subscriptions: dict[str, set] = {}  # user_id -> set of server_ids

    async def connect(self, websocket: WebSocket, user_id: str):
        """Register WebSocket connection (connection already accepted)"""
        self.active_connections[user_id] = websocket
        self.user_subscriptions[user_id] = set()
        logger.info(f"MCP WebSocket connected for user {user_id}")

    def disconnect(self, user_id: str):
        """Handle WebSocket disconnection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.user_subscriptions:
            del self.user_subscriptions[user_id]
        logger.info(f"MCP WebSocket disconnected for user {user_id}")

    async def send_message(self, user_id: str, message: dict):
        """Send message to specific user with error handling"""
        websocket = self.active_connections.get(user_id)
        if websocket:
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.warning(f"Failed to send message to user {user_id}: {e}")
                # Remove broken connection
                self.disconnect(user_id)

    async def broadcast_server_update(self, server_id: str, update: dict):
        """Broadcast server update to all subscribed users"""
        for user_id, subscriptions in self.user_subscriptions.items():
            if server_id in subscriptions:
                await self.send_message(user_id, {
                    "type": "server_update",
                    "server_id": server_id,
                    "data": update
                })

    def subscribe_to_server(self, user_id: str, server_id: str):
        """Subscribe user to server updates"""
        if user_id in self.user_subscriptions:
            self.user_subscriptions[user_id].add(server_id)

    def unsubscribe_from_server(self, user_id: str, server_id: str):
        """Unsubscribe user from server updates"""
        if user_id in self.user_subscriptions:
            self.user_subscriptions[user_id].discard(server_id)


# Global WebSocket manager instance
mcp_ws_manager = MCPWebSocketManager()

# Set up the connection between MCP manager and WebSocket manager
def setup_mcp_websocket_integration():
    """Set up integration between MCP manager and WebSocket manager"""
    from app.services.mcp_manager import mcp_manager
    mcp_manager.set_websocket_manager(mcp_ws_manager)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for MCP real-time communication

    Supports:
    - Server status updates
    - Tool execution results
    - Real-time notifications
    """
    logger.info(f"MCP WebSocket endpoint called - URL: {websocket.url}")
    session: Session | None = None
    user: User | None = None
    user_id: str | None = None

    try:
        # Accept connection first (required by FastAPI)
        logger.info("Accepting WebSocket connection...")
        await websocket.accept()
        logger.info("WebSocket connection accepted")

        # Get token from query parameters
        token = websocket.query_params.get("token")
        if not token:
            logger.warning("MCP WebSocket connection rejected: No token provided")
            await websocket.close(code=1008, reason="No authentication token")
            return

        # Validate token
        try:
            import jwt

            from app.core.config import settings

            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("sub")
            if not user_id:
                await websocket.close(code=1008, reason="Invalid token")
                return

            # Get user from database
            session = next(get_db())
            user = session.exec(select(User).where(User.id == user_id)).first()
            if not user:
                await websocket.close(code=1008, reason="User not found")
                return

        except jwt.ExpiredSignatureError:
            logger.warning("MCP WebSocket connection rejected: Expired token")
            await websocket.close(code=1008, reason="Token expired")
            return
        except Exception as e:
            logger.error(f"MCP WebSocket authentication failed: {e}")
            await websocket.close(code=1008, reason="Authentication failed")
            return

        # Set up connection in manager
        await mcp_ws_manager.connect(websocket, str(user.id))

        # Send initial connection success message
        await websocket.send_text(json.dumps({
            "type": "connection",
            "status": "connected",
            "message": "MCP WebSocket connected successfully"
        }))

        # Get user's MCP servers and send initial status
        user_servers = session.exec(
            select(MCPServer).where(MCPServer.owner_id == user.id)
        ).all()

        servers_status = []
        for server in user_servers:
            servers_status.append({
                "id": str(server.id),
                "name": server.name,
                "status": server.status,
                "transport_type": server.transport_type,
                "connected": server.status == "connected"
            })
            # Subscribe to server updates
            if server.status == "connected":
                mcp_ws_manager.subscribe_to_server(str(user.id), str(server.id))

        await websocket.send_text(json.dumps({
            "type": "servers_status",
            "data": servers_status
        }))

        # Handle incoming messages
        while True:
            try:
                # Receive message
                data = await websocket.receive_text()
                message = json.loads(data)

                logger.debug(f"MCP WebSocket received from user {user.id}: {message}")

                # Handle different message types
                msg_type = message.get("type")

                if msg_type == "ping":
                    # Respond to ping
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "timestamp": message.get("timestamp")
                    }))

                elif msg_type == "subscribe":
                    # Subscribe to server updates
                    server_id = message.get("server_id")
                    if server_id:
                        # Verify user owns the server
                        server = session.get(MCPServer, server_id)
                        if server and server.owner_id == user.id:
                            mcp_ws_manager.subscribe_to_server(str(user.id), server_id)
                            await websocket.send_text(json.dumps({
                                "type": "subscribed",
                                "server_id": server_id
                            }))

                elif msg_type == "unsubscribe":
                    # Unsubscribe from server updates
                    server_id = message.get("server_id")
                    if server_id:
                        mcp_ws_manager.unsubscribe_from_server(str(user.id), server_id)
                        await websocket.send_text(json.dumps({
                            "type": "unsubscribed",
                            "server_id": server_id
                        }))

                elif msg_type == "get_server_status":
                    # Get status of specific server
                    server_id = message.get("server_id")
                    if server_id:
                        server = session.get(MCPServer, server_id)
                        if server and server.owner_id == user.id:
                            await websocket.send_text(json.dumps({
                                "type": "server_status",
                                "server_id": server_id,
                                "data": {
                                    "status": server.status,
                                    "connected": server.status == "connected",
                                    "error": server.error_message
                                }
                            }))

                elif msg_type == "refresh_servers":
                    # Refresh all servers status
                    for server in user_servers:
                        # Check actual connection status
                        is_connected = await mcp_manager.is_server_connected(str(server.id))
                        if is_connected != (server.status == "connected"):
                            # Status changed, update database
                            server.status = "connected" if is_connected else "disconnected"
                            session.add(server)
                            session.commit()

                            # Send update
                            await websocket.send_text(json.dumps({
                                "type": "server_update",
                                "server_id": str(server.id),
                                "data": {
                                    "status": server.status,
                                    "connected": is_connected
                                }
                            }))

                else:
                    # Unknown message type
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": f"Unknown message type: {msg_type}"
                    }))

            except WebSocketDisconnect:
                logger.info(f"MCP WebSocket disconnected for user {user.id}")
                break
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON from user {user.id}: {e}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))
            except Exception as e:
                logger.error(f"MCP WebSocket error for user {user.id}: {e}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": str(e)
                }))

    except Exception as e:
        logger.error(f"MCP WebSocket connection error: {e}")
    finally:
        # Clean up
        if user_id:
            mcp_ws_manager.disconnect(user_id)
        if session:
            session.close()


# Export the WebSocket manager for use in other modules
__all__ = ["router", "mcp_ws_manager"]
