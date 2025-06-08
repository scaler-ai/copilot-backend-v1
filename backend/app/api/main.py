from fastapi import APIRouter

from app.api.routes import (
    chat,
    chat_ws,
    github_oauth,
    items,
    llm_settings,
    login,
    mcp,
    mcp_ws,
    private,
    users,
    utils,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(chat_ws.router, prefix="/chat", tags=["chat-websocket"])
api_router.include_router(github_oauth.router, prefix="/github", tags=["github-oauth"])
api_router.include_router(llm_settings.router, prefix="/llm-settings", tags=["llm-settings"])
api_router.include_router(mcp.router, prefix="/mcp", tags=["mcp"])
api_router.include_router(mcp_ws.router, prefix="/mcp", tags=["mcp-websocket"])


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
