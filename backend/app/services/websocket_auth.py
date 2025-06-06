"""
WebSocket authentication utilities
"""

import jwt
from fastapi import WebSocket
from sqlmodel import select

from app.api.deps import get_db
from app.core.config import settings
from app.models import User


async def authenticate_websocket(websocket: WebSocket) -> User | None:
    """
    Authenticate WebSocket connection using JWT token from query parameters.

    Returns:
        User object if authentication successful, None otherwise
    """
    try:
        # Get token from query parameters
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=1008, reason="Missing authentication")
            return None

        # Validate JWT token
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = payload.get("sub")
            if not user_id:
                await websocket.close(code=1008, reason="Invalid authentication")
                return None
        except jwt.ExpiredSignatureError:
            await websocket.close(code=1008, reason="Authentication expired")
            return None
        except jwt.InvalidTokenError:
            await websocket.close(code=1008, reason="Invalid authentication")
            return None

        # Get user from database
        with next(get_db()) as session:
            user = session.exec(select(User).where(User.id == user_id)).first()
            if not user:
                await websocket.close(code=1008, reason="User not found")
                return None
            return user

    except Exception:
        await websocket.close(code=1008, reason="Authentication failed")
        return None
