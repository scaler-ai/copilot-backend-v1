import logging
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlmodel import Session, select
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.main import api_router
from app.core.config import settings
from app.core.db import engine
from app.models import MCPServer
from app.services.mcp_manager import mcp_manager


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


class WebSocketCORSMiddleware(BaseHTTPMiddleware):
    """
    Custom middleware to handle WebSocket CORS.
    The standard CORS middleware doesn't handle WebSocket upgrade requests properly.
    """
    async def dispatch(self, request: Request, call_next):
        logger = logging.getLogger(__name__)
        
        # Check if this is a WebSocket upgrade request
        if request.headers.get("upgrade") == "websocket":
            # For WebSocket, we need to check the origin manually
            origin = request.headers.get("origin")
            logger.info(f"WebSocket request from origin: {origin}")
            logger.info(f"WebSocket path: {request.url.path}")
            logger.info(f"Allowed origins: {settings.all_cors_origins}")
            
            if origin and origin in settings.all_cors_origins:
                # Origin is allowed, proceed with the request
                logger.info(f"WebSocket origin {origin} is allowed")
                response = await call_next(request)
                return response
            else:
                # Origin not allowed or not present
                logger.warning(f"WebSocket origin {origin} is not allowed or missing")
                return Response(content="Origin not allowed", status_code=403)
        
        # For non-WebSocket requests, proceed normally
        return await call_next(request)


async def startup_mcp_connections():
    """
    Reconnect to enabled MCP servers on application startup.
    This ensures that servers marked as "connected" in the database
    are actually connected in the MCP manager.
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting MCP server auto-reconnection...")

    try:
        with Session(engine) as session:
            # Get all enabled MCP servers
            statement = select(MCPServer).where(MCPServer.is_enabled is True)
            servers = session.exec(statement).all()

            logger.info(f"Found {len(servers)} enabled MCP servers")

            connected_count = 0
            for server in servers:
                try:
                    # Reset status to disconnected before attempting connection
                    server.status = "disconnected"
                    server.error_message = None
                    session.add(server)
                    session.commit()

                    # Attempt to connect
                    logger.info(f"Attempting to connect to MCP server: {server.name}")
                    success = await mcp_manager.connect_server(server, session)

                    if success:
                        connected_count += 1
                        logger.info(f"Successfully connected to MCP server: {server.name}")
                    else:
                        logger.warning(f"Failed to connect to MCP server: {server.name} - {server.error_message}")

                except Exception as e:
                    logger.error(f"Error connecting to MCP server {server.name}: {e}")
                    server.status = "error"
                    server.error_message = str(e)
                    session.add(server)
                    session.commit()

            logger.info(f"MCP startup complete: {connected_count}/{len(servers)} servers connected")

    except Exception as e:
        logger.error(f"Error during MCP startup: {e}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    # Set up MCP WebSocket integration
    from app.api.routes.mcp_ws import setup_mcp_websocket_integration
    setup_mcp_websocket_integration()

    await startup_mcp_connections()
    yield
    # Shutdown
    await mcp_manager.shutdown()


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
    redirect_slashes=False,  # Disable automatic trailing slash redirects to prevent CORS issues with proxy
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Add WebSocket CORS middleware AFTER the standard CORS middleware
# Due to middleware execution order in Starlette (reverse order), this will run first
app.add_middleware(WebSocketCORSMiddleware)

app.include_router(api_router, prefix=settings.API_V1_STR)
