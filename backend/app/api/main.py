from fastapi import APIRouter

# Import routes directly
from app.api.routes import chat
from app.api.routes import chat_ws
from app.api.routes import github_oauth
from app.api.routes import items
from app.api.routes import llm_settings
from app.api.routes import login
from app.api.routes import mcp
from app.api.routes import mcp_ws
from app.api.routes import private
from app.api.routes import skills
from app.api.routes import users
from app.api.routes import utils
# New routes - import carefully
try:
    from app.api.routes import admin_skill_config
    HAS_ADMIN_SKILL_CONFIG = True
except ImportError:
    HAS_ADMIN_SKILL_CONFIG = False
    
try:
    from app.api.routes import darwinbox
    HAS_DARWINBOX = True
except ImportError:
    HAS_DARWINBOX = False
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
api_router.include_router(skills.router, prefix="/skills", tags=["skills"])
# Conditionally include new routes
if HAS_ADMIN_SKILL_CONFIG:
    api_router.include_router(admin_skill_config.router, prefix="/admin", tags=["admin"])
if HAS_DARWINBOX:
    api_router.include_router(darwinbox.router, prefix="/darwinbox", tags=["darwinbox"])


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
