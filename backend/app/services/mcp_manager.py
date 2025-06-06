import asyncio
import logging
import uuid

from sqlmodel import Session

from app.models import MCPServer
from app.services.mcp_client import MCPClient, MCPStdioTransport

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages MCP client connections"""

    def __init__(self):
        self.clients: dict[str, MCPClient] = {}
        self._lock = asyncio.Lock()
        self._ws_manager = None  # Will be set later to avoid circular imports

    async def connect_server(self, server: MCPServer, session: Session) -> bool:
        """Connect to an MCP server"""
        async with self._lock:
            server_id = str(server.id)

            # Check if already connected
            if server_id in self.clients:
                existing_client = self.clients[server_id]
                if existing_client.is_connected():
                    logger.info(f"MCP server {server.name} is already connected")
                    return True
                else:
                    # Clean up disconnected client
                    await self._cleanup_client(server_id)

            try:
                # Update server status
                server.status = "connecting"
                server.error_message = None
                session.add(server)
                session.commit()

                # Create transport based on server configuration
                transport = await self._create_transport(server)
                if not transport:
                    raise Exception("Failed to create transport")

                # Create and connect client
                client = MCPClient(transport)
                success = await client.connect()

                if success:
                    # Store client
                    self.clients[server_id] = client

                    # Update server with connection info
                    server.status = "connected"
                    server.error_message = None
                    server.capabilities = {
                        "tools": {},
                        "resources": {},
                        "prompts": {}
                    }
                    server.tools = client.get_tools()
                    server.resources = client.get_resources()
                    server.prompts = client.get_prompts()

                    session.add(server)
                    session.commit()

                    logger.info(f"Successfully connected to MCP server: {server.name}")

                    # Notify WebSocket clients about successful connection
                    await self._notify_server_status_change(server_id, "connected")
                    return True
                else:
                    raise Exception("Failed to establish MCP connection")

            except Exception as e:
                logger.error(f"Failed to connect to MCP server {server.name}: {e}")

                # Update server status with error
                server.status = "error"
                server.error_message = str(e)
                session.add(server)
                session.commit()

                # Notify WebSocket clients about connection error
                await self._notify_server_status_change(server_id, "error", str(e))

                # Clean up failed client
                await self._cleanup_client(server_id)
                return False

    async def disconnect_server(self, server: MCPServer, session: Session) -> bool:
        """Disconnect from an MCP server"""
        async with self._lock:
            server_id = str(server.id)

            try:
                # Disconnect client if exists
                if server_id in self.clients:
                    client = self.clients[server_id]
                    await client.disconnect()
                    del self.clients[server_id]

                # Update server status
                server.status = "disconnected"
                server.error_message = None
                server.capabilities = None
                server.tools = None
                server.resources = None
                server.prompts = None

                session.add(server)
                session.commit()

                logger.info(f"Disconnected from MCP server: {server.name}")

                # Notify WebSocket clients about disconnection
                await self._notify_server_status_change(server_id, "disconnected")
                return True

            except Exception as e:
                logger.error(f"Failed to disconnect from MCP server {server.name}: {e}")
                server.status = "error"
                server.error_message = str(e)
                session.add(server)
                session.commit()
                return False

    async def get_client(self, server_id: uuid.UUID) -> MCPClient | None:
        """Get MCP client for a server"""
        server_id_str = str(server_id)
        client = self.clients.get(server_id_str)

        if client and client.is_connected():
            return client
        elif client:
            # Clean up disconnected client
            await self._cleanup_client(server_id_str)

        return None

    async def call_tool(self, server_id: uuid.UUID, tool_name: str, arguments: dict) -> dict:
        """Call a tool on an MCP server"""
        client = await self.get_client(server_id)
        if not client:
            raise Exception("MCP server is not connected")

        try:
            result = await client.call_tool(tool_name, arguments)
            return {
                "success": True,
                "result": result,
                "tool": tool_name,
                "arguments": arguments
            }
        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "tool": tool_name,
                "arguments": arguments
            }

    async def read_resource(self, server_id: uuid.UUID, uri: str) -> dict:
        """Read a resource from an MCP server"""
        client = await self.get_client(server_id)
        if not client:
            raise Exception("MCP server is not connected")

        try:
            result = await client.read_resource(uri)
            return {
                "success": True,
                "result": result,
                "uri": uri
            }
        except Exception as e:
            logger.error(f"Resource read failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "uri": uri
            }

    async def get_prompt(self, server_id: uuid.UUID, prompt_name: str, arguments: dict) -> dict:
        """Get a prompt from an MCP server"""
        client = await self.get_client(server_id)
        if not client:
            raise Exception("MCP server is not connected")

        try:
            result = await client.get_prompt(prompt_name, arguments)
            return {
                "success": True,
                "result": result,
                "prompt": prompt_name,
                "arguments": arguments
            }
        except Exception as e:
            logger.error(f"Prompt get failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "prompt": prompt_name,
                "arguments": arguments
            }

    def set_websocket_manager(self, ws_manager):
        """Set the WebSocket manager for real-time notifications"""
        self._ws_manager = ws_manager

    async def _notify_server_status_change(self, server_id: str, status: str, error: str | None = None):
        """Notify WebSocket clients about server status changes"""
        if self._ws_manager:
            await self._ws_manager.broadcast_server_update(server_id, {
                "status": status,
                "connected": status == "connected",
                "error": error
            })

    async def is_server_connected(self, server_id: str) -> bool:
        """Check if a specific server is connected"""
        client = self.clients.get(server_id)
        return client is not None and client.is_connected()

    async def health_check(self) -> dict[str, any]:
        """Check health of all connected servers"""
        status = {
            "connected_servers": len(self.clients),
            "servers": {}
        }

        for server_id, client in self.clients.items():
            status["servers"][server_id] = {
                "connected": client.is_connected(),
                "tools_count": len(client.tools),
                "resources_count": len(client.resources),
                "prompts_count": len(client.prompts)
            }

        return status

    async def shutdown(self):
        """Shutdown all MCP connections"""
        async with self._lock:
            logger.info("Shutting down MCP manager...")

            # Disconnect all clients
            disconnect_tasks = []
            for server_id in list(self.clients.keys()):
                task = asyncio.create_task(self._cleanup_client(server_id))
                disconnect_tasks.append(task)

            if disconnect_tasks:
                await asyncio.gather(*disconnect_tasks, return_exceptions=True)

            self.clients.clear()
            logger.info("MCP manager shutdown complete")

    async def _create_transport(self, server: MCPServer):
        """Create transport for MCP server based on configuration"""
        if server.transport == "stdio":
            if not server.command:
                raise ValueError("stdio transport requires command")

            # Use the command and args fields directly
            command = server.command
            args = server.args or []

            # If args field is empty but command contains spaces, fall back to splitting
            # This maintains backward compatibility with existing servers
            if not args and " " in command:
                command_parts = command.split()
                command = command_parts[0]
                args = command_parts[1:]

            # Prepare environment variables
            env = {}
            if server.auth_config:
                # Add auth config as environment variables
                for key, value in server.auth_config.items():
                    if isinstance(value, str):
                        env[key] = value  # Use original key names, not MCP_ prefixed

            return MCPStdioTransport(command, args, env)

        elif server.transport == "http_sse":
            # TODO: Implement HTTP+SSE transport
            raise NotImplementedError("HTTP+SSE transport not yet implemented")
        else:
            raise ValueError(f"Unsupported transport: {server.transport}")

    async def _cleanup_client(self, server_id: str):
        """Clean up a client connection"""
        if server_id in self.clients:
            try:
                client = self.clients[server_id]
                await client.disconnect()
            except Exception as e:
                logger.error(f"Error cleaning up client {server_id}: {e}")
            finally:
                del self.clients[server_id]


# Global MCP manager instance
mcp_manager = MCPManager()
