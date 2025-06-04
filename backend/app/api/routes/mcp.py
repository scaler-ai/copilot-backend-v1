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
from app.services.mcp_manager import mcp_manager

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
async def connect_server(
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

    # Use MCP manager to connect
    success = await mcp_manager.connect_server(server, session)

    # Refresh server to get updated status
    session.refresh(server)

    if success:
        return MCPConnectionStatus(
            server_id=server.id,
            status=server.status,
            message="Successfully connected to MCP server"
        )
    else:
        return MCPConnectionStatus(
            server_id=server.id,
            status=server.status,
            message=server.error_message or "Failed to connect to MCP server"
        )


@router.post("/servers/{server_id}/disconnect", response_model=MCPConnectionStatus)
async def disconnect_server(
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

    # Use MCP manager to disconnect
    success = await mcp_manager.disconnect_server(server, session)

    # Refresh server to get updated status
    session.refresh(server)

    if success:
        return MCPConnectionStatus(
            server_id=server.id,
            status=server.status,
            message="Successfully disconnected from MCP server"
        )
    else:
        return MCPConnectionStatus(
            server_id=server.id,
            status=server.status,
            message=server.error_message or "Failed to disconnect from MCP server"
        )


@router.post("/servers/{server_id}/tools/{tool_name}/call")
async def call_tool(
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

    # Use MCP manager to call tool
    try:
        result = await mcp_manager.call_tool(server_id, tool_name, arguments or {})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/servers/{server_id}/resources/{resource_uri:path}")
async def get_resource(
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

    # Use MCP manager to read resource
    try:
        result = await mcp_manager.read_resource(server_id, resource_uri)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{server_id}/prompts/{prompt_name}")
async def get_prompt(
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

    # Use MCP manager to get prompt
    try:
        result = await mcp_manager.get_prompt(server_id, prompt_name, arguments or {})
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def mcp_health_check() -> Any:
    """
    Get health status of MCP manager and connections.
    """
    try:
        health_status = await mcp_manager.health_check()
        return health_status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
