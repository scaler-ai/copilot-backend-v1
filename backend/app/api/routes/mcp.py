import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    MCPConnectionStatus,
    MCPServer,
    MCPServerCreate,
    MCPServerPublic,
    MCPServersPublic,
    MCPServerUpdate,
    Message,
)

router = APIRouter()


@router.get("/servers", response_model=MCPServersPublic)
def read_servers(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve MCP servers for the current user.
    """
    count_statement = select(func.count()).select_from(MCPServer).where(MCPServer.owner_id == current_user.id)
    count = session.exec(count_statement).one()

    statement = (
        select(MCPServer)
        .where(MCPServer.owner_id == current_user.id)
        .offset(skip)
        .limit(limit)
    )
    servers = session.exec(statement).all()

    return MCPServersPublic(data=servers, count=count)


@router.get("/servers/{server_id}", response_model=MCPServerPublic)
def read_server(session: SessionDep, current_user: CurrentUser, server_id: uuid.UUID) -> Any:
    """
    Get MCP server by ID.
    """
    server = session.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    if server.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return server


@router.post("/servers", response_model=MCPServerPublic)
def create_server(
    *, session: SessionDep, current_user: CurrentUser, server_in: MCPServerCreate
) -> Any:
    """
    Create new MCP server.
    """
    server = MCPServer.model_validate(server_in, update={"owner_id": current_user.id})
    session.add(server)
    session.commit()
    session.refresh(server)
    return server


@router.put("/servers/{server_id}", response_model=MCPServerPublic)
def update_server(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    server_id: uuid.UUID,
    server_in: MCPServerUpdate,
) -> Any:
    """
    Update an MCP server.
    """
    server = session.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    if server.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    update_dict = server_in.model_dump(exclude_unset=True)
    server.sqlmodel_update(update_dict)
    session.add(server)
    session.commit()
    session.refresh(server)
    return server


@router.delete("/servers/{server_id}")
def delete_server(
    session: SessionDep, current_user: CurrentUser, server_id: uuid.UUID
) -> Message:
    """
    Delete an MCP server.
    """
    server = session.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    if server.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    session.delete(server)
    session.commit()
    return Message(message="MCP Server deleted successfully")


@router.post("/servers/{server_id}/connect", response_model=MCPConnectionStatus)
def connect_server(
    session: SessionDep, current_user: CurrentUser, server_id: uuid.UUID
) -> Any:
    """
    Connect to an MCP server.
    """
    server = session.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    if server.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    if not server.is_enabled:
        raise HTTPException(status_code=400, detail="Server is disabled")

    # Update server status to connecting
    server.status = "connecting"
    server.error_message = None
    session.add(server)
    session.commit()

    # TODO: Implement actual MCP connection logic here
    # For now, simulate a successful connection
    try:
        # Simulate connection process
        # This would normally involve:
        # 1. Establishing transport (stdio or HTTP+SSE)
        # 2. Performing MCP handshake
        # 3. Getting server capabilities, tools, resources, prompts

        # Mock successful connection
        server.status = "connected"
        server.capabilities = {
            "tools": {},
            "resources": {},
            "prompts": {}
        }
        server.tools = []
        server.resources = []
        server.prompts = []

        session.add(server)
        session.commit()
        session.refresh(server)

        return MCPConnectionStatus(
            server_id=server.id,
            status="connected",
            message="Successfully connected to MCP server"
        )

    except Exception as e:
        # Handle connection error
        server.status = "error"
        server.error_message = str(e)
        session.add(server)
        session.commit()

        return MCPConnectionStatus(
            server_id=server.id,
            status="error",
            message=f"Failed to connect: {str(e)}"
        )


@router.post("/servers/{server_id}/disconnect", response_model=MCPConnectionStatus)
def disconnect_server(
    session: SessionDep, current_user: CurrentUser, server_id: uuid.UUID
) -> Any:
    """
    Disconnect from an MCP server.
    """
    server = session.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    if server.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    # TODO: Implement actual MCP disconnection logic here
    # For now, simulate disconnection

    server.status = "disconnected"
    server.error_message = None
    server.capabilities = None
    server.tools = None
    server.resources = None
    server.prompts = None

    session.add(server)
    session.commit()
    session.refresh(server)

    return MCPConnectionStatus(
        server_id=server.id,
        status="disconnected",
        message="Successfully disconnected from MCP server"
    )


@router.post("/servers/{server_id}/tools/{tool_name}/call")
def call_tool(
    session: SessionDep,
    current_user: CurrentUser,
    server_id: uuid.UUID,
    tool_name: str,
    arguments: dict = None
) -> Any:
    """
    Call a tool on an MCP server.
    """
    server = session.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    if server.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    if server.status != "connected":
        raise HTTPException(status_code=400, detail="Server is not connected")

    # TODO: Implement actual tool calling logic
    # For now, return a mock response
    return {
        "tool": tool_name,
        "arguments": arguments or {},
        "result": f"Mock result for tool '{tool_name}' with arguments {arguments}",
        "timestamp": "2025-01-06T00:00:00Z"
    }


@router.get("/servers/{server_id}/resources/{resource_uri:path}")
def get_resource(
    session: SessionDep,
    current_user: CurrentUser,
    server_id: uuid.UUID,
    resource_uri: str
) -> Any:
    """
    Get a resource from an MCP server.
    """
    server = session.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    if server.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    if server.status != "connected":
        raise HTTPException(status_code=400, detail="Server is not connected")

    # TODO: Implement actual resource retrieval logic
    # For now, return a mock response
    return {
        "uri": resource_uri,
        "content": f"Mock content for resource '{resource_uri}'",
        "mimeType": "text/plain",
        "timestamp": "2025-01-06T00:00:00Z"
    }


@router.post("/servers/{server_id}/prompts/{prompt_name}")
def get_prompt(
    session: SessionDep,
    current_user: CurrentUser,
    server_id: uuid.UUID,
    prompt_name: str,
    arguments: dict = None
) -> Any:
    """
    Get a prompt from an MCP server.
    """
    server = session.get(MCPServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="MCP Server not found")
    if server.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    if server.status != "connected":
        raise HTTPException(status_code=400, detail="Server is not connected")

    # TODO: Implement actual prompt retrieval logic
    # For now, return a mock response
    return {
        "prompt": prompt_name,
        "arguments": arguments or {},
        "content": f"Mock prompt content for '{prompt_name}' with arguments {arguments}",
        "timestamp": "2025-01-06T00:00:00Z"
    }
