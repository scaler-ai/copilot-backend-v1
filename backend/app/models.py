import uuid
from typing import Any

from pydantic import EmailStr
from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=40)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=40)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=40)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=40)
    new_password: str = Field(min_length=8, max_length=40)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)
    mcp_servers: list["MCPServer"] = Relationship(back_populates="owner", cascade_delete=True)
    chat_conversations: list["ChatConversation"] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: str | None = Field(default=None, min_length=1, max_length=255)  # type: ignore


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=40)


# MCP Server Models
class MCPServerBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    transport: str = Field(regex="^(stdio|http_sse)$")  # Transport type
    command: str | None = Field(default=None, max_length=1000)  # For stdio transport
    url: str | None = Field(default=None, max_length=500)  # For http_sse transport
    is_remote: bool = Field(default=False)  # Remote vs local server
    is_enabled: bool = Field(default=True)  # Whether server can be connected
    auth_type: str | None = Field(default=None, regex="^(bearer|api_key|basic)$")  # Authentication type


class MCPServerCreate(MCPServerBase):
    auth_config: Any | None = Field(default=None)  # Auth configuration


class MCPServerUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    transport: str | None = Field(default=None, regex="^(stdio|http_sse)$")
    command: str | None = Field(default=None, max_length=1000)
    url: str | None = Field(default=None, max_length=500)
    is_remote: bool | None = Field(default=None)
    is_enabled: bool | None = Field(default=None)
    auth_type: str | None = Field(default=None, regex="^(bearer|api_key|basic)$")
    auth_config: Any | None = Field(default=None)


# Database model
class MCPServer(MCPServerBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    status: str = Field(default="disconnected")  # connected|connecting|disconnected|error
    error_message: str | None = Field(default=None, max_length=1000)
    auth_config: Any | None = Field(default=None, sa_column=Column(JSON))  # Auth configuration (JSON)
    capabilities: Any | None = Field(default=None, sa_column=Column(JSON))  # Server capabilities (JSON)
    tools: Any | None = Field(default=None, sa_column=Column(JSON))  # Available tools (JSON)
    resources: Any | None = Field(default=None, sa_column=Column(JSON))  # Available resources (JSON)
    prompts: Any | None = Field(default=None, sa_column=Column(JSON))  # Available prompts (JSON)
    owner_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    owner: User | None = Relationship(back_populates="mcp_servers")


# Public model for API responses
class MCPServerPublic(MCPServerBase):
    id: uuid.UUID
    status: str
    error_message: str | None
    auth_config: Any | None
    capabilities: Any | None
    tools: Any | None
    resources: Any | None
    prompts: Any | None
    owner_id: uuid.UUID


class MCPServersPublic(SQLModel):
    data: list[MCPServerPublic]
    count: int


# Connection status response
class MCPConnectionStatus(SQLModel):
    server_id: uuid.UUID
    status: str
    message: str


# Chat Models
class ChatMessage(SQLModel):
    message: str = Field(min_length=1, max_length=5000)
    conversation_id: str | None = Field(default=None, max_length=100)


class ChatToolCall(SQLModel):
    server_id: str
    server_name: str
    tool_name: str
    parameters: dict[str, Any]
    result: dict[str, Any]
    success: bool


class ChatResponse(SQLModel):
    response: str
    tool_calls: list[ChatToolCall]
    servers_used: list[str]
    conversation_id: str | None
    error: str | None = None


# Database models for chat persistence
class ChatConversation(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID as string
    title: str | None = Field(default=None, max_length=255)
    created_at: str = Field(default_factory=lambda: __import__('datetime').datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: __import__('datetime').datetime.utcnow().isoformat())
    message_count: int = Field(default=0)
    owner_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    owner: User | None = Relationship(back_populates="chat_conversations")


class ChatMessageDB(SQLModel, table=True):
    __tablename__ = "chat_message"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    conversation_id: str = Field(foreign_key="chatconversation.id", nullable=False, ondelete="CASCADE")
    message_type: str = Field(max_length=20)  # 'user', 'assistant', 'error'
    content: str = Field(max_length=10000)
    timestamp: str = Field(default_factory=lambda: __import__('datetime').datetime.utcnow().isoformat())
    tool_calls: Any | None = Field(default=None, sa_column=Column(JSON))  # Store tool call results
    servers_used: Any | None = Field(default=None, sa_column=Column(JSON))  # Store server names
    extra_metadata: Any | None = Field(default=None, sa_column=Column(JSON))  # Additional metadata
    
    conversation: ChatConversation | None = Relationship()


# Public models for API responses
class ChatConversationPublic(SQLModel):
    id: str
    title: str | None
    created_at: str
    updated_at: str
    message_count: int
    owner_id: uuid.UUID


class ChatMessagePublic(SQLModel):
    id: uuid.UUID
    conversation_id: str
    message_type: str
    content: str
    timestamp: str
    tool_calls: Any | None
    servers_used: Any | None
    extra_metadata: Any | None


class ChatConversationsPublic(SQLModel):
    data: list[ChatConversationPublic]
    count: int


class ChatMessagesPublic(SQLModel):
    data: list[ChatMessagePublic]
    count: int
