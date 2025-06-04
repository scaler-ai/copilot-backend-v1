import asyncio
import json
import logging
import os
import subprocess
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class MCPMessage(BaseModel):
    """MCP JSON-RPC message structure"""
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str | None = None
    params: dict[str, Any] | None = None
    result: Any | None = None
    error: dict[str, Any] | None = None


class MCPCapabilities(BaseModel):
    """MCP server capabilities"""
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None


class MCPTool(BaseModel):
    """MCP tool definition"""
    name: str
    description: str | None = None
    inputSchema: dict[str, Any] | None = None


class MCPResource(BaseModel):
    """MCP resource definition"""
    uri: str
    name: str | None = None
    description: str | None = None
    mimeType: str | None = None


class MCPPrompt(BaseModel):
    """MCP prompt definition"""
    name: str
    description: str | None = None
    arguments: list[dict[str, Any]] | None = None


class MCPStdioTransport:
    """Stdio transport for MCP servers"""

    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.process: subprocess.Popen | None = None
        self.request_id = 0
        self.pending_requests: dict[str | int, asyncio.Future] = {}

    async def connect(self) -> bool:
        """Start the MCP server process"""
        try:
            # Expand environment variables in command
            expanded_command = os.path.expandvars(self.command)
            expanded_args = [os.path.expandvars(arg) for arg in self.args]

            # Prepare environment
            env = os.environ.copy()
            env.update(self.env)

            # Start the process
            self.process = subprocess.Popen(
                [expanded_command] + expanded_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                bufsize=0  # Unbuffered
            )

            logger.info(f"Started MCP server: {expanded_command} {' '.join(expanded_args)}")
            return True

        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            return False

    async def disconnect(self):
        """Stop the MCP server process"""
        if self.process:
            try:
                self.process.terminate()
                # Wait up to 5 seconds for graceful shutdown
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't shut down gracefully
                    self.process.kill()
                    self.process.wait()
                logger.info("MCP server process terminated")
            except Exception as e:
                logger.error(f"Error terminating MCP server: {e}")
            finally:
                self.process = None

        # Cancel any pending requests
        for future in self.pending_requests.values():
            if not future.done():
                future.cancel()
        self.pending_requests.clear()

    def is_connected(self) -> bool:
        """Check if the transport is connected"""
        return self.process is not None and self.process.poll() is None

    async def send_request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and wait for response"""
        if not self.is_connected():
            raise ConnectionError("MCP server is not connected")

        # Generate unique request ID
        self.request_id += 1
        request_id = self.request_id

        # Create request message
        message = MCPMessage(
            id=request_id,
            method=method,
            params=params or {}
        )

        # Create future for response
        future = asyncio.Future()
        self.pending_requests[request_id] = future

        try:
            # Send the request
            request_data = message.model_dump(exclude_none=True)
            request_json = json.dumps(request_data) + "\n"

            logger.debug(f"Sending MCP request: {request_json.strip()}")
            self.process.stdin.write(request_json)
            self.process.stdin.flush()

            # Wait for response (with timeout)
            response = await asyncio.wait_for(future, timeout=30.0)
            return response

        except asyncio.TimeoutError:
            logger.error(f"MCP request timeout: {method}")
            raise TimeoutError(f"MCP request timeout: {method}")
        except Exception as e:
            logger.error(f"MCP request failed: {e}")
            raise
        finally:
            # Clean up pending request
            self.pending_requests.pop(request_id, None)

    async def send_notification(self, method: str, params: dict[str, Any] | None = None):
        """Send a JSON-RPC notification (no response expected)"""
        if not self.is_connected():
            raise ConnectionError("MCP server is not connected")

        # Create notification message (no ID)
        message = MCPMessage(
            method=method,
            params=params or {}
        )

        # Send the notification
        request_data = message.model_dump(exclude_none=True)
        # Remove id field for notifications
        request_data.pop('id', None)
        request_json = json.dumps(request_data) + "\n"

        logger.debug(f"Sending MCP notification: {request_json.strip()}")
        self.process.stdin.write(request_json)
        self.process.stdin.flush()

    async def read_responses(self):
        """Read responses from the MCP server (should run in background)"""
        if not self.process or not self.process.stdout:
            return

        try:
            while self.is_connected():
                # Read line from stdout
                line = await asyncio.get_event_loop().run_in_executor(
                    None, self.process.stdout.readline
                )

                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                logger.debug(f"Received MCP response: {line}")

                try:
                    # Parse JSON response
                    response_data = json.loads(line)
                    response = MCPMessage(**response_data)

                    # Handle response or notification
                    if response.id is not None:
                        # This is a response to a request
                        future = self.pending_requests.get(response.id)
                        if future and not future.done():
                            if response.error:
                                error = Exception(f"MCP Error: {response.error}")
                                future.set_exception(error)
                            else:
                                future.set_result(response.result)
                    else:
                        # This is a notification from server
                        logger.info(f"Received MCP notification: {response.method}")
                        # Handle server notifications here if needed

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse MCP response: {e}")
                except Exception as e:
                    logger.error(f"Error handling MCP response: {e}")

        except Exception as e:
            logger.error(f"Error reading MCP responses: {e}")


class MCPClient:
    """High-level MCP client"""

    def __init__(self, transport: MCPStdioTransport):
        self.transport = transport
        self.capabilities: MCPCapabilities | None = None
        self.tools: list[MCPTool] = []
        self.resources: list[MCPResource] = []
        self.prompts: list[MCPPrompt] = []
        self._reader_task: asyncio.Task | None = None

    async def connect(self) -> bool:
        """Connect to MCP server and perform handshake"""
        try:
            # Start transport
            if not await self.transport.connect():
                return False

            # Start background reader task
            self._reader_task = asyncio.create_task(self.transport.read_responses())

            # Perform MCP handshake
            await self._initialize_client()

            # Get server capabilities
            await self._get_capabilities()

            logger.info("MCP client connected successfully")
            return True

        except Exception as e:
            logger.error(f"MCP connection failed: {e}")
            await self.disconnect()
            return False

    async def disconnect(self):
        """Disconnect from MCP server"""
        try:
            # Cancel reader task
            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass

            # Disconnect transport
            await self.transport.disconnect()

            # Clear state
            self.capabilities = None
            self.tools.clear()
            self.resources.clear()
            self.prompts.clear()

            logger.info("MCP client disconnected")

        except Exception as e:
            logger.error(f"Error during MCP disconnect: {e}")

    async def _initialize_client(self):
        """Send initialize request to MCP server"""
        params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {}
            },
            "clientInfo": {
                "name": "copilot-backend",
                "version": "1.0.0"
            }
        }

        result = await self.transport.send_request("initialize", params)
        logger.info(f"MCP server initialized: {result}")

        # Send initialized notification
        await self.transport.send_notification("notifications/initialized")

    async def _get_capabilities(self):
        """Get server capabilities and available tools/resources/prompts"""
        try:
            # Get tools list
            try:
                tools_result = await self.transport.send_request("tools/list")
                if tools_result and "tools" in tools_result:
                    self.tools = [MCPTool(**tool) for tool in tools_result["tools"]]
                    logger.info(f"Loaded {len(self.tools)} tools")
            except Exception as e:
                logger.warning(f"Failed to get tools: {e}")

            # Get resources list
            try:
                resources_result = await self.transport.send_request("resources/list")
                if resources_result and "resources" in resources_result:
                    self.resources = [MCPResource(**resource) for resource in resources_result["resources"]]
                    logger.info(f"Loaded {len(self.resources)} resources")
            except Exception as e:
                logger.warning(f"Failed to get resources: {e}")

            # Get prompts list
            try:
                prompts_result = await self.transport.send_request("prompts/list")
                if prompts_result and "prompts" in prompts_result:
                    self.prompts = [MCPPrompt(**prompt) for prompt in prompts_result["prompts"]]
                    logger.info(f"Loaded {len(self.prompts)} prompts")
            except Exception as e:
                logger.warning(f"Failed to get prompts: {e}")

        except Exception as e:
            logger.error(f"Failed to get capabilities: {e}")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the MCP server"""
        params = {
            "name": name,
            "arguments": arguments
        }
        return await self.transport.send_request("tools/call", params)

    async def read_resource(self, uri: str) -> Any:
        """Read a resource from the MCP server"""
        params = {
            "uri": uri
        }
        return await self.transport.send_request("resources/read", params)

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Get a prompt from the MCP server"""
        params = {
            "name": name,
            "arguments": arguments or {}
        }
        return await self.transport.send_request("prompts/get", params)

    def is_connected(self) -> bool:
        """Check if client is connected"""
        return self.transport.is_connected()

    def get_tools(self) -> list[dict[str, Any]]:
        """Get list of available tools"""
        return [tool.model_dump() for tool in self.tools]

    def get_resources(self) -> list[dict[str, Any]]:
        """Get list of available resources"""
        return [resource.model_dump() for resource in self.resources]

    def get_prompts(self) -> list[dict[str, Any]]:
        """Get list of available prompts"""
        return [prompt.model_dump() for prompt in self.prompts]
