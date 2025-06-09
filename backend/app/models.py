import uuid
from datetime import datetime
from typing import Any, Optional

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
    llm_settings: Optional["LLMSettings"] = Relationship(back_populates="owner", cascade_delete=True, sa_relationship_kwargs={"uselist": False})
    github_oauth: Optional["GitHubOAuth"] = Relationship(back_populates="owner", cascade_delete=True, sa_relationship_kwargs={"uselist": False})
    scaler_crm_auth: Optional["ScalerCRMAuth"] = Relationship(back_populates="owner", cascade_delete=True, sa_relationship_kwargs={"uselist": False})
    skills: list["UserSkill"] = Relationship(back_populates="owner", cascade_delete=True)
    # discovered_github_organizations: list["GitHubOrganization"] = Relationship(back_populates="discovered_by", cascade_delete=True)


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
    args: list[str] | None = Field(default=None)  # Command arguments for stdio transport
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
    args: list[str] | None = Field(default=None)
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
    args: list[str] | None = Field(default=None, sa_column=Column(JSON))  # Command arguments (JSON)
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
    args: list[str] | None
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
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
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


# LLM Settings Models
class LLMSettingsBase(SQLModel):
    provider: str = Field(max_length=50)  # 'openai', 'anthropic', 'google', 'azure', etc.
    model: str = Field(max_length=100)  # 'gpt-4', 'claude-3-5-sonnet', 'gemini-pro', etc.
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2000, ge=1, le=8000)
    is_active: bool = Field(default=True)


class LLMSettingsCreate(LLMSettingsBase):
    api_key: str = Field(min_length=1, max_length=500)  # Will be encrypted before storage


class LLMSettingsUpdate(SQLModel):
    provider: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=100)
    api_key: str | None = Field(default=None, min_length=1, max_length=500)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=8000)
    is_active: bool | None = Field(default=None)


# Database model
class LLMSettings(LLMSettingsBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    encrypted_api_key: str = Field(max_length=1000)  # Encrypted API key
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    owner_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE", unique=True)
    owner: User | None = Relationship(back_populates="llm_settings")


# Public model for API responses (excludes API key)
class LLMSettingsPublic(LLMSettingsBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    owner_id: uuid.UUID
    # Note: API key is never included in public responses


# LLM Provider and Model definitions
class LLMProvider(SQLModel):
    name: str
    display_name: str
    models: list[str]
    requires_api_key: bool
    default_model: str
    max_tokens_limit: int


class LLMProvidersResponse(SQLModel):
    providers: list[LLMProvider]


# GitHub OAuth Integration Models
class GitHubOAuthBase(SQLModel):
    github_username: str = Field(max_length=255)
    avatar_url: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=1000)
    public_repos: int | None = Field(default=None)
    followers: int | None = Field(default=None)
    following: int | None = Field(default=None)
    scopes: str = Field(max_length=500)  # Comma-separated list of granted scopes
    is_active: bool = Field(default=True)


# Database model
class GitHubOAuth(GitHubOAuthBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    github_id: int = Field(unique=True, index=True)  # GitHub user ID
    encrypted_access_token: str = Field(max_length=1000)  # Encrypted OAuth token
    token_expires_at: str | None = Field(default=None)  # When token expires (if applicable)
    refresh_token: str | None = Field(default=None, max_length=1000)  # For token refresh
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_sync_at: str | None = Field(default=None)  # Last time we synced with GitHub
    owner_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE", unique=True)
    owner: User | None = Relationship(back_populates="github_oauth")


# Public model for API responses (excludes tokens)
class GitHubOAuthPublic(GitHubOAuthBase):
    id: uuid.UUID
    github_id: int
    created_at: str
    updated_at: str
    last_sync_at: str | None
    owner_id: uuid.UUID
    # Note: Access tokens are never included in public responses


# Request/Response models for OAuth flow
class GitHubOAuthCallback(SQLModel):
    code: str = Field(min_length=1)
    state: str | None = Field(default=None)


class GitHubOAuthResponse(SQLModel):
    success: bool
    message: str
    github_oauth: GitHubOAuthPublic | None = Field(default=None)


class GitHubOAuthSettings(SQLModel):
    """Settings for GitHub OAuth integration"""
    client_id: str = Field(min_length=1, max_length=100)
    client_secret: str = Field(min_length=1, max_length=100)
    redirect_uri: str = Field(min_length=1, max_length=500)
    scopes: list[str] = Field(default=["repo", "read:user", "user:email", "read:org", "read:discussion", "read:project"])


# Skill Mapping Models
class UserSkillBase(SQLModel):
    skill_id: str = Field(max_length=255, index=True)  # References skills-taxonomy.yaml
    skill_name: str = Field(max_length=255)  # Cached from taxonomy for performance
    skill_level: str = Field(max_length=50)  # Text level or SFIA level
    proficiency_score: int | None = Field(default=None, ge=1, le=100)  # Optional 1-100 score
    years_experience: float | None = Field(default=None, ge=0)  # Years of experience
    is_verified: bool = Field(default=False)  # Whether skill has been verified
    last_used: str | None = Field(default=None)  # When skill was last used (YYYY-MM format)
    learning_status: str = Field(default="active", max_length=50)  # active, learning, rusty, deprecated
    notes: str | None = Field(default=None, max_length=1000)  # Personal notes about the skill
    sfia_level: int | None = Field(default=None, ge=1, le=7)  # SFIA numeric level (1-7)
    sfia_code: str | None = Field(default=None, max_length=10)  # Cached SFIA code from taxonomy


# Database model for user skills
class UserSkill(UserSkillBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    owner_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    owner: User | None = Relationship(back_populates="skills")
    
    # Relationships
    endorsements: list["SkillEndorsement"] = Relationship(back_populates="user_skill", cascade_delete=True)
    assessments: list["SkillAssessment"] = Relationship(back_populates="user_skill", cascade_delete=True)


# Public model for API responses
class UserSkillPublic(UserSkillBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    owner_id: uuid.UUID
    endorsement_count: int = Field(default=0)
    latest_assessment_score: int | None = Field(default=None)


# Request models
class UserSkillCreate(SQLModel):
    skill_id: str = Field(min_length=1, max_length=255)
    skill_level: str = Field(min_length=1)  # Support both SFIA levels (1-7) and text levels
    proficiency_score: int | None = Field(default=None, ge=1, le=100)
    years_experience: float | None = Field(default=None, ge=0)
    last_used: str | None = Field(default=None, regex="^[0-9]{4}-[0-9]{2}$")  # YYYY-MM format
    learning_status: str = Field(default="active", regex="^(active|learning|rusty|deprecated)$")
    notes: str | None = Field(default=None, max_length=1000)
    sfia_level: int | None = Field(default=None, ge=1, le=7)  # SFIA numeric level


class UserSkillUpdate(SQLModel):
    skill_level: str | None = Field(default=None)  # Support both SFIA and text levels
    proficiency_score: int | None = Field(default=None, ge=1, le=100)
    years_experience: float | None = Field(default=None, ge=0)
    last_used: str | None = Field(default=None, regex="^[0-9]{4}-[0-9]{2}$")
    learning_status: str | None = Field(default=None, regex="^(active|learning|rusty|deprecated)$")
    notes: str | None = Field(default=None, max_length=1000)
    sfia_level: int | None = Field(default=None, ge=1, le=7)  # SFIA numeric level


# Skill Endorsement Models
class SkillEndorsementBase(SQLModel):
    comment: str | None = Field(default=None, max_length=500)
    strength: int = Field(ge=1, le=5, default=5)  # 1-5 rating of skill strength


class SkillEndorsement(SkillEndorsementBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    user_skill_id: uuid.UUID = Field(foreign_key="userskill.id", nullable=False, ondelete="CASCADE")
    endorsed_by_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    
    # Relationships
    user_skill: UserSkill | None = Relationship(back_populates="endorsements")
    endorsed_by: User | None = Relationship()


class SkillEndorsementPublic(SkillEndorsementBase):
    id: uuid.UUID
    created_at: str
    endorsed_by_name: str = Field(max_length=255)
    endorsed_by_id: uuid.UUID


class SkillEndorsementCreate(SQLModel):
    user_skill_id: uuid.UUID
    comment: str | None = Field(default=None, max_length=500)
    strength: int = Field(ge=1, le=5, default=5)


# Skill Assessment Models  
class SkillAssessmentBase(SQLModel):
    assessment_type: str = Field(max_length=100)  # self, peer, manager, formal_test
    score: int = Field(ge=1, le=100)
    max_score: int = Field(default=100, ge=1)
    assessor_notes: str | None = Field(default=None, max_length=1000)
    assessment_date: str = Field(default_factory=lambda: datetime.utcnow().date().isoformat())


class SkillAssessment(SkillAssessmentBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    user_skill_id: uuid.UUID = Field(foreign_key="userskill.id", nullable=False, ondelete="CASCADE")
    assessor_id: uuid.UUID | None = Field(foreign_key="user.id", nullable=True, ondelete="SET NULL")
    
    # Relationships
    user_skill: UserSkill | None = Relationship(back_populates="assessments")
    assessor: User | None = Relationship()


class SkillAssessmentPublic(SkillAssessmentBase):
    id: uuid.UUID
    created_at: str
    assessor_name: str | None = Field(default=None, max_length=255)


class SkillAssessmentCreate(SQLModel):
    user_skill_id: uuid.UUID
    assessment_type: str = Field(regex="^(self|peer|manager|formal_test)$")
    score: int = Field(ge=1, le=100)
    max_score: int = Field(default=100, ge=1)
    assessor_notes: str | None = Field(default=None, max_length=1000)


# Team/Project Skill Requirements
class SkillRequirementBase(SQLModel):
    skill_id: str = Field(max_length=255)
    skill_name: str = Field(max_length=255)  # Cached from taxonomy
    required_level: str = Field(max_length=50)  # beginner, intermediate, advanced, expert
    importance: str = Field(default="required", max_length=50)  # required, preferred, nice_to_have
    description: str | None = Field(default=None, max_length=500)


class SkillRequirement(SkillRequirementBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    created_by_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    
    # Context - what this requirement is for
    context_type: str = Field(max_length=100)  # project, team, role, position
    context_id: str = Field(max_length=255)  # ID of the project/team/role
    context_name: str = Field(max_length=255)  # Human readable name
    
    # Relationships
    created_by: User | None = Relationship()


class SkillRequirementPublic(SkillRequirementBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    context_type: str
    context_id: str
    context_name: str
    created_by_name: str = Field(max_length=255)


class SkillRequirementCreate(SQLModel):
    skill_id: str = Field(min_length=1, max_length=255)
    required_level: str = Field(regex="^(beginner|intermediate|advanced|expert)$")
    importance: str = Field(default="required", regex="^(required|preferred|nice_to_have)$")
    description: str | None = Field(default=None, max_length=500)
    context_type: str = Field(min_length=1, max_length=100)
    context_id: str = Field(min_length=1, max_length=255)
    context_name: str = Field(min_length=1, max_length=255)


# Skill Gap Analysis Models
class SkillGap(SQLModel):
    """Model for skill gap analysis results"""
    skill_id: str
    skill_name: str
    required_level: str
    current_level: str | None = Field(default=None)
    gap_severity: str  # critical, major, minor, none
    has_skill: bool = Field(default=False)
    proficiency_score: int | None = Field(default=None)
    recommendation: str | None = Field(default=None)


class SkillMatchResult(SQLModel):
    """Model for skill matching results"""
    user_id: uuid.UUID
    user_name: str
    match_percentage: float = Field(ge=0, le=100)
    skill_matches: list[dict[str, Any]] = Field(default_factory=list)
    skill_gaps: list[SkillGap] = Field(default_factory=list)
    overall_score: float = Field(ge=0, le=100)


# Response models for complex operations
class UserSkillsResponse(SQLModel):
    skills: list[UserSkillPublic]
    total_count: int
    by_category: dict[str, int] = Field(default_factory=dict)
    by_level: dict[str, int] = Field(default_factory=dict)


class SkillTaxonomyResponse(SQLModel):
    """Response model for skill taxonomy data"""
    categories: dict[str, Any]
    skill_levels: dict[str, Any]
    skill_pathways: dict[str, Any]
    version: str
    last_updated: str


class SkillAnalyticsResponse(SQLModel):
    """Response model for skill analytics"""
    total_skills: int
    skills_by_category: dict[str, int]
    skills_by_level: dict[str, int]
    top_skills: list[dict[str, Any]]
    skill_trends: list[dict[str, Any]]
    certification_stats: dict[str, int]


# GitHub Organization Models
class GitHubOrganizationBase(SQLModel):
    name: str = Field(max_length=255, index=True)
    description: str | None = Field(default=None, max_length=1000)
    html_url: str = Field(max_length=500)
    avatar_url: str | None = Field(default=None, max_length=500)
    public_repos: int | None = Field(default=None)
    followers: int | None = Field(default=None)
    following: int | None = Field(default=None)
    location: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    blog: str | None = Field(default=None, max_length=500)
    company: str | None = Field(default=None, max_length=255)
    twitter_username: str | None = Field(default=None, max_length=255)


class GitHubOrganization(GitHubOrganizationBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    github_id: int = Field(unique=True, index=True)  # GitHub organization ID
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_sync_at: str | None = Field(default=None)
    
    # Track who discovered/added this organization
    discovered_by_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    # discovered_by: User | None = Relationship()
    
    # Relationships
    # contributors: list["GitHubContributor"] = Relationship(back_populates="organization", cascade_delete=True)


class GitHubOrganizationPublic(GitHubOrganizationBase):
    id: uuid.UUID
    github_id: int
    created_at: str
    updated_at: str
    last_sync_at: str | None
    contributor_count: int = Field(default=0)
    repository_count: int = Field(default=0)


# GitHub Contributor Models
class GitHubContributorBase(SQLModel):
    login: str = Field(max_length=255, index=True)
    avatar_url: str | None = Field(default=None, max_length=500)
    html_url: str = Field(max_length=500)
    type: str = Field(max_length=50)  # User, Bot, etc.
    site_admin: bool = Field(default=False)
    name: str | None = Field(default=None, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    blog: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=1000)
    public_repos: int | None = Field(default=None)
    followers: int | None = Field(default=None)
    following: int | None = Field(default=None)
    hireable: bool | None = Field(default=None)
    total_contributions: int = Field(default=0)
    is_organization_member: bool = Field(default=False)


class GitHubContributor(GitHubContributorBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    github_id: int = Field(index=True)  # GitHub user ID
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_sync_at: str | None = Field(default=None)
    
    # Organization relationship
    organization_id: uuid.UUID = Field(foreign_key="githuborganization.id", nullable=False, ondelete="CASCADE")
    # organization: GitHubOrganization | None = Relationship(back_populates="contributors")
    
    # Repository contributions
    repository_contributions: list["GitHubRepositoryContribution"] = Relationship(back_populates="contributor", cascade_delete=True)
    
    # Enhanced activity tracking
    activities: list["GitHubActivity"] = Relationship(back_populates="contributor", cascade_delete=True)
    pull_requests: list["GitHubPullRequest"] = Relationship(back_populates="contributor", cascade_delete=True)
    issue_activities: list["GitHubIssueActivity"] = Relationship(back_populates="contributor", cascade_delete=True)
    skill_analyses: list["ContributorAnalysis"] = Relationship(back_populates="contributor", cascade_delete=True)


class GitHubContributorPublic(GitHubContributorBase):
    id: uuid.UUID
    github_id: int
    created_at: str
    updated_at: str
    last_sync_at: str | None
    repository_count: int = Field(default=0)
    repositories: list[dict[str, Any]] = Field(default_factory=list)


# GitHub Repository Contribution Models
class GitHubRepositoryContributionBase(SQLModel):
    repository_name: str = Field(max_length=255, index=True)
    repository_url: str = Field(max_length=500)
    contributions: int = Field(default=0)
    repository_description: str | None = Field(default=None, max_length=1000)
    repository_language: str | None = Field(default=None, max_length=100)
    repository_stars: int | None = Field(default=None)
    repository_forks: int | None = Field(default=None)
    is_fork: bool = Field(default=False)
    is_private: bool = Field(default=False)


class GitHubRepositoryContribution(GitHubRepositoryContributionBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    repository_id: int | None = Field(default=None, index=True)  # GitHub repository ID
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Contributor relationship
    contributor_id: uuid.UUID = Field(foreign_key="githubcontributor.id", nullable=False, ondelete="CASCADE")
    contributor: GitHubContributor | None = Relationship(back_populates="repository_contributions")


class GitHubRepositoryContributionPublic(GitHubRepositoryContributionBase):
    id: uuid.UUID
    repository_id: int | None
    created_at: str
    updated_at: str


# Response models for GitHub API endpoints
class GitHubOrganizationContributorsResponse(SQLModel):
    organization: str
    total_contributors: int
    total_repositories: int
    page: int
    per_page: int
    total_pages: int
    contributors: list[dict[str, Any]]


class GitHubContributorAnalytics(SQLModel):
    contributor_login: str
    total_contributions: int
    repository_count: int
    top_languages: list[str]
    contribution_distribution: dict[str, int]  # repo_name -> contributions
    activity_level: str  # high, medium, low based on contributions
    contributor_type: str  # core, regular, occasional


class GitHubOrganizationAnalytics(SQLModel):
    organization_name: str
    total_contributors: int
    total_repositories: int
    top_contributors: list["GitHubContributorAnalytics"]
    language_distribution: dict[str, int]
    contribution_trends: dict[str, Any]
    activity_summary: dict[str, int]


# Enhanced GitHub Activity Models for Skill Analysis

# Base models for GitHub activities
class GitHubActivityBase(SQLModel):
    activity_type: str = Field(max_length=100)  # pr_created, pr_reviewed, issue_created, comment_left, commit_made
    repository_name: str = Field(max_length=255, index=True)
    repository_url: str = Field(max_length=500)
    title: str = Field(max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    programming_languages: str | None = Field(default=None, max_length=500)  # JSON string of languages
    complexity_indicators: str | None = Field(default=None, max_length=1000)  # JSON string of complexity metrics
    github_created_at: str  # When the activity was created on GitHub
    github_url: str = Field(max_length=500)


class GitHubActivity(GitHubActivityBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    github_activity_id: str = Field(max_length=255, index=True)  # GitHub's unique ID for the activity
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Contributor relationship
    contributor_id: uuid.UUID = Field(foreign_key="githubcontributor.id", nullable=False, ondelete="CASCADE")
    contributor: GitHubContributor | None = Relationship(back_populates="activities")


class GitHubActivityPublic(GitHubActivityBase):
    id: uuid.UUID
    github_activity_id: str
    created_at: str
    updated_at: str


# Enhanced Pull Request model
class GitHubPullRequestBase(SQLModel):
    github_pr_id: int = Field(index=True)
    repository_name: str = Field(max_length=255, index=True)
    repository_url: str = Field(max_length=500)
    title: str = Field(max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    state: str = Field(max_length=50)  # open, closed, merged
    additions: int = Field(default=0)
    deletions: int = Field(default=0)
    changed_files: int = Field(default=0)
    programming_languages: str | None = Field(default=None, max_length=500)  # JSON string
    code_complexity_score: int | None = Field(default=None, ge=1, le=100)
    review_comments_received: int = Field(default=0)
    review_comments_given: int = Field(default=0)
    commits_count: int = Field(default=0)
    is_draft: bool = Field(default=False)
    merged_at: str | None = Field(default=None)
    closed_at: str | None = Field(default=None)
    github_created_at: str
    github_updated_at: str


class GitHubPullRequest(GitHubPullRequestBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Contributor relationship
    contributor_id: uuid.UUID = Field(foreign_key="githubcontributor.id", nullable=False, ondelete="CASCADE")
    contributor: GitHubContributor | None = Relationship(back_populates="pull_requests")
    
    # Reviews relationship
    reviews_received: list["GitHubCodeReview"] = Relationship(back_populates="pull_request")


class GitHubPullRequestPublic(GitHubPullRequestBase):
    id: uuid.UUID
    created_at: str
    updated_at: str


# Code Review model
class GitHubCodeReviewBase(SQLModel):
    github_review_id: int | None = Field(default=None, index=True)
    review_type: str = Field(max_length=50)  # approve, request_changes, comment, dismiss
    comment_count: int = Field(default=0)
    technical_depth_score: int | None = Field(default=None, ge=1, le=100)
    review_quality_indicators: str | None = Field(default=None, max_length=1000)  # JSON string
    github_submitted_at: str


class GitHubCodeReview(GitHubCodeReviewBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Relationships
    reviewer_id: uuid.UUID = Field(foreign_key="githubcontributor.id", nullable=False, ondelete="CASCADE")
    reviewer: GitHubContributor | None = Relationship()
    
    pull_request_id: uuid.UUID = Field(foreign_key="githubpullrequest.id", nullable=False, ondelete="CASCADE")
    pull_request: GitHubPullRequest | None = Relationship(back_populates="reviews_received")


class GitHubCodeReviewPublic(GitHubCodeReviewBase):
    id: uuid.UUID
    created_at: str
    updated_at: str


# Issue Activity model
class GitHubIssueActivityBase(SQLModel):
    github_issue_id: int = Field(index=True)
    repository_name: str = Field(max_length=255, index=True)
    repository_url: str = Field(max_length=500)
    issue_title: str = Field(max_length=500)
    issue_description: str | None = Field(default=None, max_length=2000)
    activity_type: str = Field(max_length=50)  # created, commented, closed, assigned
    comment_content: str | None = Field(default=None, max_length=2000)
    labels: str | None = Field(default=None, max_length=500)  # JSON string of issue labels
    is_bug: bool = Field(default=False)
    is_enhancement: bool = Field(default=False)
    github_created_at: str


class GitHubIssueActivity(GitHubIssueActivityBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Contributor relationship
    contributor_id: uuid.UUID = Field(foreign_key="githubcontributor.id", nullable=False, ondelete="CASCADE")
    contributor: GitHubContributor | None = Relationship(back_populates="issue_activities")


class GitHubIssueActivityPublic(GitHubIssueActivityBase):
    id: uuid.UUID
    created_at: str
    updated_at: str


# Skill Analysis Models
class ContributorAnalysisBase(SQLModel):
    technical_summary: str = Field(max_length=5000)  # LLM-generated summary
    skill_inferences: str = Field(max_length=5000)  # JSON string of inferred skills
    career_level_assessment: str = Field(max_length=2000)  # LLM assessment of career level
    strengths: str | None = Field(default=None, max_length=2000)  # JSON string
    improvement_areas: str | None = Field(default=None, max_length=2000)  # JSON string
    confidence_score: int = Field(default=50, ge=1, le=100)  # Overall confidence in analysis
    analysis_period_months: int = Field(default=12)  # Period analyzed
    total_activities_analyzed: int = Field(default=0)


class ContributorAnalysis(ContributorAnalysisBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Contributor relationship
    contributor_id: uuid.UUID = Field(foreign_key="githubcontributor.id", nullable=False, ondelete="CASCADE")
    contributor: GitHubContributor | None = Relationship(back_populates="skill_analyses")
    
    # User who requested the analysis
    generated_by_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE")
    generated_by: User | None = Relationship()


class ContributorAnalysisPublic(ContributorAnalysisBase):
    id: uuid.UUID
    generated_at: str
    updated_at: str


# Skill Rating from GitHub Analysis
class GitHubSkillRatingBase(SQLModel):
    skill_id: str = Field(max_length=255, index=True)
    skill_name: str = Field(max_length=255)
    inferred_level: int = Field(ge=1, le=7)  # SFIA levels 1-7
    confidence_score: int = Field(ge=1, le=100)
    evidence_summary: str = Field(max_length=2000)
    github_evidence_count: int = Field(default=0)  # Number of GitHub activities supporting this rating
    recommended_next_level: int | None = Field(default=None, ge=1, le=7)
    improvement_suggestions: str | None = Field(default=None, max_length=1000)


class GitHubSkillRating(GitHubSkillRatingBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Analysis relationship
    analysis_id: uuid.UUID = Field(foreign_key="contributoranalysis.id", nullable=False, ondelete="CASCADE")
    analysis: ContributorAnalysis | None = Relationship()


class GitHubSkillRatingPublic(GitHubSkillRatingBase):
    id: uuid.UUID
    generated_at: str


# Response models for GitHub skill analysis APIs
class GitHubSkillAnalysisResponse(SQLModel):
    overall_assessment: str
    skill_ratings: list[GitHubSkillRatingPublic]
    strengths: list[str]
    growth_areas: list[str]
    learning_recommendations: list[str]
    next_level_requirements: list[str]
    confidence_score: int
    last_updated: str


class ContributorDetailedActivityResponse(SQLModel):
    contributor: GitHubContributorPublic
    activities: list[GitHubActivityPublic]
    pull_requests: list[GitHubPullRequestPublic]
    code_reviews: list[GitHubCodeReviewPublic]
    issue_activities: list[GitHubIssueActivityPublic]
    activity_summary: dict[str, Any]
    period_analyzed: str
    total_activities: int


class SkillProgressResponse(SQLModel):
    skill_id: str
    skill_name: str
    current_level: int
    target_level: int
    progress_percentage: float
    recent_evidence: list[str]
    recommended_actions: list[str]
    estimated_timeline: str


# Scaler CRM Models
class ScalerCRMAuthBase(SQLModel):
    crm_user_email: EmailStr = Field(max_length=255, index=True)
    crm_user_id: str | None = Field(default=None, max_length=255)  # CRM user ID after successful auth
    crm_user_name: str | None = Field(default=None, max_length=255)
    is_active: bool = Field(default=True)
    last_sync_at: str | None = Field(default=None)
    sync_status: str = Field(default="pending", max_length=50)  # pending, syncing, completed, failed


# Database model
class ScalerCRMAuth(ScalerCRMAuthBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    encrypted_access_token: str = Field(max_length=1000)  # Encrypted CRM access token
    encrypted_refresh_token: str | None = Field(default=None, max_length=1000)  # Encrypted refresh token
    token_expires_at: str | None = Field(default=None)  # When access token expires
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    owner_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE", unique=True)
    owner: User | None = Relationship()
    
    # Relationships
    leads: list["ScalerLead"] = Relationship(back_populates="crm_auth", cascade_delete=True)
    activities: list["ScalerActivity"] = Relationship(back_populates="crm_auth", cascade_delete=True)
    conversations: list["ScalerConversation"] = Relationship(back_populates="crm_auth", cascade_delete=True)
    performance_analyses: list["SalesPerformanceAnalysis"] = Relationship(back_populates="crm_auth", cascade_delete=True)


# Public model for API responses (excludes tokens)
class ScalerCRMAuthPublic(ScalerCRMAuthBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    owner_id: uuid.UUID


# Request models
class ScalerCRMAuthConnect(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=1, max_length=100)  # Will not be stored


class ScalerCRMAuthResponse(SQLModel):
    success: bool
    message: str
    crm_auth: ScalerCRMAuthPublic | None = Field(default=None)


# Scaler Lead Models
class ScalerLeadBase(SQLModel):
    lead_id: str = Field(max_length=255, index=True)  # CRM lead ID
    lead_name: str = Field(max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    company: str | None = Field(default=None, max_length=255)
    designation: str | None = Field(default=None, max_length=255)
    lead_source: str | None = Field(default=None, max_length=100)
    lead_status: str = Field(max_length=100)  # new, contacted, qualified, etc.
    lead_stage: str | None = Field(default=None, max_length=100)  # awareness, consideration, decision
    lead_score: int | None = Field(default=None, ge=0, le=100)
    created_date: str | None = Field(default=None)  # From CRM
    last_activity_date: str | None = Field(default=None)
    assigned_to: str | None = Field(default=None, max_length=255)  # Sales rep name
    assigned_to_id: str | None = Field(default=None, max_length=255)  # Sales rep ID in CRM


class ScalerLead(ScalerLeadBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    raw_data: Any | None = Field(default=None, sa_column=Column(JSON))  # Complete CRM response
    
    # CRM Auth relationship
    crm_auth_id: uuid.UUID = Field(foreign_key="scalercrmauth.id", nullable=False, ondelete="CASCADE")
    crm_auth: ScalerCRMAuth | None = Relationship(back_populates="leads")
    
    # Lead activities and conversations
    activities: list["ScalerActivity"] = Relationship(back_populates="lead", cascade_delete=True)
    conversations: list["ScalerConversation"] = Relationship(back_populates="lead", cascade_delete=True)


class ScalerLeadPublic(ScalerLeadBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    activity_count: int = Field(default=0)
    conversation_count: int = Field(default=0)


# Scaler Activity Models
class ScalerActivityBase(SQLModel):
    activity_id: str = Field(max_length=255, index=True)  # CRM activity ID
    activity_type: str = Field(max_length=100)  # call, email, meeting, whatsapp, task
    activity_subject: str | None = Field(default=None, max_length=500)
    activity_description: str | None = Field(default=None, max_length=5000)
    activity_date: str = Field(index=True)  # ISO date string
    duration_minutes: int | None = Field(default=None, ge=0)
    outcome: str | None = Field(default=None, max_length=100)  # successful, no_answer, scheduled, etc.
    next_action: str | None = Field(default=None, max_length=500)
    sentiment: str | None = Field(default=None, max_length=50)  # positive, neutral, negative
    engagement_score: int | None = Field(default=None, ge=1, le=10)


class ScalerActivity(ScalerActivityBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    raw_data: Any | None = Field(default=None, sa_column=Column(JSON))
    
    # Relationships
    crm_auth_id: uuid.UUID = Field(foreign_key="scalercrmauth.id", nullable=False, ondelete="CASCADE")
    crm_auth: ScalerCRMAuth | None = Relationship(back_populates="activities")
    
    lead_id: uuid.UUID | None = Field(foreign_key="scalerlead.id", nullable=True, ondelete="CASCADE")
    lead: ScalerLead | None = Relationship(back_populates="activities")


class ScalerActivityPublic(ScalerActivityBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    lead_name: str | None = Field(default=None)


# Scaler Conversation Models (for transcript analysis)
class ScalerConversationBase(SQLModel):
    conversation_id: str = Field(max_length=255, index=True)  # CRM conversation ID
    conversation_type: str = Field(max_length=50)  # call, chat, email
    conversation_date: str = Field(index=True)
    duration_seconds: int | None = Field(default=None, ge=0)
    transcript_available: bool = Field(default=False)
    recording_url: str | None = Field(default=None, max_length=500)
    analysis_status: str = Field(default="pending", max_length=50)  # pending, analyzing, completed, failed


class ScalerConversation(ScalerConversationBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    transcript_text: str | None = Field(default=None, max_length=50000)  # Full transcript
    transcript_summary: str | None = Field(default=None, max_length=2000)  # AI-generated summary
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    analyzed_at: str | None = Field(default=None)
    raw_data: Any | None = Field(default=None, sa_column=Column(JSON))
    
    # Relationships
    crm_auth_id: uuid.UUID = Field(foreign_key="scalercrmauth.id", nullable=False, ondelete="CASCADE")
    crm_auth: ScalerCRMAuth | None = Relationship(back_populates="conversations")
    
    lead_id: uuid.UUID | None = Field(foreign_key="scalerlead.id", nullable=True, ondelete="CASCADE")
    lead: ScalerLead | None = Relationship(back_populates="conversations")
    
    # Analysis results
    feedback_items: list["ConversationFeedback"] = Relationship(back_populates="conversation", cascade_delete=True)


class ScalerConversationPublic(ScalerConversationBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    analyzed_at: str | None
    has_feedback: bool = Field(default=False)
    feedback_count: int = Field(default=0)


# Conversation Feedback Models
class ConversationFeedbackBase(SQLModel):
    feedback_type: str = Field(max_length=100)  # strength, improvement, technique, missed_opportunity
    feedback_category: str = Field(max_length=100)  # communication, discovery, objection_handling, closing
    feedback_text: str = Field(max_length=2000)
    specific_moment: str | None = Field(default=None, max_length=500)  # Timestamp or quote
    suggested_response: str | None = Field(default=None, max_length=1000)
    impact_level: str = Field(default="medium", max_length=50)  # high, medium, low
    confidence_score: int = Field(ge=1, le=100)


class ConversationFeedback(ConversationFeedbackBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Conversation relationship
    conversation_id: uuid.UUID = Field(foreign_key="scalerconversation.id", nullable=False, ondelete="CASCADE")
    conversation: ScalerConversation | None = Relationship(back_populates="feedback_items")


class ConversationFeedbackPublic(ConversationFeedbackBase):
    id: uuid.UUID
    created_at: str


# Sales Performance Analysis Models
class SalesPerformanceAnalysisBase(SQLModel):
    analysis_period_start: str = Field(index=True)  # ISO date
    analysis_period_end: str = Field(index=True)  # ISO date
    total_leads: int = Field(default=0)
    total_activities: int = Field(default=0)
    total_conversations: int = Field(default=0)
    conversion_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    average_response_time_hours: float | None = Field(default=None, ge=0.0)
    average_deal_size: float | None = Field(default=None, ge=0.0)
    activity_breakdown: Any = Field(sa_column=Column(JSON))  # {call: 20, email: 30, etc}
    lead_stage_distribution: Any = Field(sa_column=Column(JSON))  # {new: 10, contacted: 20, etc}
    performance_summary: str = Field(max_length=5000)  # LLM-generated summary
    strengths_identified: Any = Field(sa_column=Column(JSON))  # List of strengths
    improvement_areas: Any = Field(sa_column=Column(JSON))  # List of improvement areas


class SalesPerformanceAnalysis(SalesPerformanceAnalysisBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # CRM Auth relationship
    crm_auth_id: uuid.UUID = Field(foreign_key="scalercrmauth.id", nullable=False, ondelete="CASCADE")
    crm_auth: ScalerCRMAuth | None = Relationship(back_populates="performance_analyses")
    
    # Skill ratings from this analysis
    skill_ratings: list["SalesSkillRating"] = Relationship(back_populates="analysis", cascade_delete=True)


class SalesPerformanceAnalysisPublic(SalesPerformanceAnalysisBase):
    id: uuid.UUID
    generated_at: str
    updated_at: str
    skill_ratings_count: int = Field(default=0)


# Sales Skill Rating Models
class SalesSkillRatingBase(SQLModel):
    skill_id: str = Field(max_length=255, index=True)  # References skills-taxonomy.yaml
    skill_name: str = Field(max_length=255)
    skill_category: str = Field(max_length=100)  # communication, relationship, closing, etc.
    inferred_level: int = Field(ge=1, le=5)  # 1-5 scale for sales skills
    confidence_score: int = Field(ge=1, le=100)
    evidence_summary: str = Field(max_length=2000)
    evidence_count: int = Field(default=0)  # Number of activities/conversations supporting this
    improvement_suggestions: str | None = Field(default=None, max_length=1000)


class SalesSkillRating(SalesSkillRatingBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Analysis relationship
    analysis_id: uuid.UUID = Field(foreign_key="salesperformanceanalysis.id", nullable=False, ondelete="CASCADE")
    analysis: SalesPerformanceAnalysis | None = Relationship(back_populates="skill_ratings")


class SalesSkillRatingPublic(SalesSkillRatingBase):
    id: uuid.UUID
    generated_at: str


# Response models for sales APIs
class SalesPerformanceResponse(SQLModel):
    current_performance: SalesPerformanceAnalysisPublic
    skill_ratings: list[SalesSkillRatingPublic]
    recent_conversations: list[ScalerConversationPublic]
    activity_trends: dict[str, Any]
    learning_recommendations: list[str]


class ConversationAnalysisResponse(SQLModel):
    conversation: ScalerConversationPublic
    feedback_items: list[ConversationFeedbackPublic]
    overall_assessment: str
    key_moments: list[dict[str, Any]]
    skill_demonstrations: list[dict[str, Any]]
    next_steps: list[str]


class TeamPerformanceResponse(SQLModel):
    team_members: list[dict[str, Any]]  # Basic info about team members
    aggregate_metrics: dict[str, Any]
    top_performers: list[dict[str, Any]]
    team_strengths: list[str]
    team_improvement_areas: list[str]
    collaboration_score: float


# DarwinBox Models
class DarwinBoxEmployeeBase(SQLModel):
    darwinbox_id: str = Field(max_length=255, index=True, unique=True)  # DarwinBox employee ID
    employee_code: str | None = Field(default=None, max_length=100)  # Employee code
    full_name: str = Field(max_length=255)
    email: EmailStr = Field(max_length=255, index=True)
    designation: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    reporting_manager_id: str | None = Field(default=None, max_length=255)
    reporting_manager_name: str | None = Field(default=None, max_length=255)
    date_of_joining: str | None = Field(default=None)  # ISO date string
    employment_status: str = Field(default="active", max_length=50)  # active, inactive, terminated
    phone_number: str | None = Field(default=None, max_length=50)
    grade: str | None = Field(default=None, max_length=50)
    business_unit: str | None = Field(default=None, max_length=255)
    cost_center: str | None = Field(default=None, max_length=255)
    is_manager: bool = Field(default=False)
    employee_type: str | None = Field(default=None, max_length=50)  # full_time, part_time, contractor


# Database model
class DarwinBoxEmployee(DarwinBoxEmployeeBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    last_sync_at: str | None = Field(default=None)
    synced_by_id: uuid.UUID | None = Field(foreign_key="user.id", nullable=True, ondelete="SET NULL")
    
    # Additional metadata from DarwinBox
    raw_data: Any | None = Field(default=None, sa_column=Column(JSON))  # Store complete API response
    
    # Relationships
    github_mapping: Optional["EmployeeGitHubMapping"] = Relationship(
        back_populates="darwinbox_employee", 
        cascade_delete=True,
        sa_relationship_kwargs={"uselist": False}
    )
    managed_teams: list["TeamStructure"] = Relationship(
        back_populates="manager",
        sa_relationship_kwargs={"foreign_keys": "[TeamStructure.manager_id]"}
    )


# Public model for API responses
class DarwinBoxEmployeePublic(DarwinBoxEmployeeBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    last_sync_at: str | None
    has_github_mapping: bool = Field(default=False)
    github_username: str | None = Field(default=None)
    team_count: int = Field(default=0)


class DarwinBoxEmployeesPublic(SQLModel):
    data: list[DarwinBoxEmployeePublic]
    count: int


# Request models
class DarwinBoxEmployeeCreate(SQLModel):
    darwinbox_id: str = Field(min_length=1, max_length=255)
    employee_code: str | None = Field(default=None, max_length=100)
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr = Field(max_length=255)
    designation: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    reporting_manager_id: str | None = Field(default=None, max_length=255)
    reporting_manager_name: str | None = Field(default=None, max_length=255)
    date_of_joining: str | None = Field(default=None)
    employment_status: str = Field(default="active", regex="^(active|inactive|terminated)$")
    phone_number: str | None = Field(default=None, max_length=50)
    grade: str | None = Field(default=None, max_length=50)
    business_unit: str | None = Field(default=None, max_length=255)
    cost_center: str | None = Field(default=None, max_length=255)
    is_manager: bool = Field(default=False)
    employee_type: str | None = Field(default=None, regex="^(full_time|part_time|contractor)$")
    raw_data: Any | None = Field(default=None)


class DarwinBoxEmployeeUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    employee_code: str | None = Field(default=None, max_length=100)
    designation: str | None = Field(default=None, max_length=255)
    department: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    reporting_manager_id: str | None = Field(default=None, max_length=255)
    reporting_manager_name: str | None = Field(default=None, max_length=255)
    date_of_joining: str | None = Field(default=None)
    employment_status: str | None = Field(default=None, regex="^(active|inactive|terminated)$")
    phone_number: str | None = Field(default=None, max_length=50)
    grade: str | None = Field(default=None, max_length=50)
    business_unit: str | None = Field(default=None, max_length=255)
    cost_center: str | None = Field(default=None, max_length=255)
    is_manager: bool | None = Field(default=None)
    employee_type: str | None = Field(default=None, regex="^(full_time|part_time|contractor)$")
    raw_data: Any | None = Field(default=None)


# Employee to GitHub Mapping Models
class EmployeeGitHubMappingBase(SQLModel):
    github_username: str = Field(max_length=255, index=True)  # GitHub username
    github_id: int | None = Field(default=None, index=True)  # GitHub numeric ID
    mapping_verified: bool = Field(default=False)  # Whether the mapping has been verified
    verification_method: str | None = Field(default=None, max_length=100)  # How it was verified
    verification_notes: str | None = Field(default=None, max_length=500)  # Additional notes


# Database model
class EmployeeGitHubMapping(EmployeeGitHubMappingBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # DarwinBox employee relationship
    darwinbox_employee_id: uuid.UUID = Field(
        foreign_key="darwinboxemployee.id", 
        nullable=False, 
        ondelete="CASCADE",
        unique=True
    )
    darwinbox_employee: DarwinBoxEmployee | None = Relationship(back_populates="github_mapping")
    
    # Who created this mapping
    mapped_by_id: uuid.UUID = Field(
        foreign_key="user.id", 
        nullable=False, 
        ondelete="CASCADE"
    )
    mapped_by: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[EmployeeGitHubMapping.mapped_by_id]"}
    )


# Public model for API responses
class EmployeeGitHubMappingPublic(EmployeeGitHubMappingBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    verified_at: str | None
    darwinbox_employee_id: uuid.UUID
    github_user_id: uuid.UUID
    mapped_by_id: uuid.UUID
    darwinbox_employee_name: str = Field(max_length=255)
    github_username: str = Field(max_length=255)
    mapped_by_name: str = Field(max_length=255)


class EmployeeGitHubMappingsPublic(SQLModel):
    data: list[EmployeeGitHubMappingPublic]
    count: int


# Request models
class EmployeeGitHubMappingCreate(SQLModel):
    darwinbox_employee_id: uuid.UUID
    github_user_id: uuid.UUID
    mapping_method: str = Field(regex="^(manual|auto_email|auto_name|admin_assigned)$")
    mapping_confidence: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = Field(default=None, max_length=1000)


class EmployeeGitHubMappingUpdate(SQLModel):
    mapping_status: str | None = Field(default=None, regex="^(active|pending|inactive)$")
    mapping_confidence: int | None = Field(default=None, ge=1, le=100)
    notes: str | None = Field(default=None, max_length=1000)
    verified_at: str | None = Field(default=None)


# Team Structure Models
class TeamStructureBase(SQLModel):
    team_name: str = Field(max_length=255, index=True)
    team_code: str | None = Field(default=None, max_length=100)
    department: str = Field(max_length=255, index=True)
    division: str | None = Field(default=None, max_length=255)
    team_size: int = Field(default=0, ge=0)
    team_type: str = Field(default="functional", max_length=50)  # functional, project, cross_functional
    is_active: bool = Field(default=True)
    parent_team_id: uuid.UUID | None = Field(default=None)  # For hierarchical teams


# Database model
class TeamStructure(TeamStructureBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # Manager relationship (DarwinBox employee)
    manager_id: uuid.UUID | None = Field(
        foreign_key="darwinboxemployee.id", 
        nullable=True, 
        ondelete="SET NULL"
    )
    manager: DarwinBoxEmployee | None = Relationship(
        back_populates="managed_teams",
        sa_relationship_kwargs={"foreign_keys": "[TeamStructure.manager_id]"}
    )
    
    # Created by relationship
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id", 
        nullable=False, 
        ondelete="CASCADE"
    )
    created_by: User | None = Relationship()
    
    # Team metadata
    team_metadata: Any | None = Field(default=None, sa_column=Column(JSON))  # Additional team info


# Public model for API responses
class TeamStructurePublic(TeamStructureBase):
    id: uuid.UUID
    created_at: str
    updated_at: str
    manager_name: str | None = Field(default=None, max_length=255)
    created_by_name: str = Field(max_length=255)


class TeamStructuresPublic(SQLModel):
    data: list[TeamStructurePublic]
    count: int


# Request models
class TeamStructureCreate(SQLModel):
    team_name: str = Field(min_length=1, max_length=255)
    team_code: str | None = Field(default=None, max_length=100)
    department: str = Field(min_length=1, max_length=255)
    division: str | None = Field(default=None, max_length=255)
    team_type: str = Field(default="functional", regex="^(functional|project|cross_functional)$")
    manager_id: uuid.UUID | None = Field(default=None)
    parent_team_id: uuid.UUID | None = Field(default=None)
    team_metadata: Any | None = Field(default=None)


class TeamStructureUpdate(SQLModel):
    team_name: str | None = Field(default=None, max_length=255)
    team_code: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=255)
    division: str | None = Field(default=None, max_length=255)
    team_size: int | None = Field(default=None, ge=0)
    team_type: str | None = Field(default=None, regex="^(functional|project|cross_functional)$")
    is_active: bool | None = Field(default=None)
    manager_id: uuid.UUID | None = Field(default=None)
    parent_team_id: uuid.UUID | None = Field(default=None)
    team_metadata: Any | None = Field(default=None)


# DarwinBox Sync Status Model
class DarwinBoxSyncStatus(SQLModel):
    sync_type: str  # employees, teams, full
    status: str  # running, completed, failed
    started_at: str
    completed_at: str | None
    total_records: int
    processed_records: int
    failed_records: int
    error_message: str | None
    sync_metadata: dict[str, Any]


# Response models for DarwinBox APIs
class DarwinBoxEmployeeAnalytics(SQLModel):
    total_employees: int
    active_employees: int
    departments: dict[str, int]
    locations: dict[str, int]
    employment_types: dict[str, int]
    github_mapping_stats: dict[str, int]
    team_distribution: dict[str, int]


class EmployeeGitHubMappingAnalytics(SQLModel):
    total_mappings: int
    mapping_methods: dict[str, int]
    mapping_confidence_distribution: dict[str, int]
    unmapped_employees: int
    pending_verifications: int
    mapping_coverage_percentage: float


class TeamHierarchyResponse(SQLModel):
    team: TeamStructurePublic
    parent_team: TeamStructurePublic | None
    sub_teams: list[TeamStructurePublic]
    team_members: list[DarwinBoxEmployeePublic]
    total_members: int


# DarwinBox Sync Request/Response Models
class DarwinBoxSyncRequest(SQLModel):
    sync_type: str = Field(regex="^(employees|teams|mappings|full)$")  # Type of sync to perform
    force_update: bool = Field(default=False)  # Force update even if recently synced
    department_filter: str | None = Field(default=None, max_length=255)  # Optional department filter
    location_filter: str | None = Field(default=None, max_length=255)  # Optional location filter
    include_inactive: bool = Field(default=False)  # Include inactive employees/teams
    batch_size: int = Field(default=100, ge=10, le=1000)  # Number of records to process per batch
    dry_run: bool = Field(default=False)  # Preview changes without committing
    metadata: dict[str, Any] | None = Field(default=None)  # Additional sync parameters


class DarwinBoxSyncResponse(SQLModel):
    sync_id: str = Field(max_length=100)  # Unique ID for this sync operation
    status: str = Field(regex="^(initiated|in_progress|completed|failed|cancelled)$")
    message: str
    sync_type: str
    started_at: str
    estimated_completion_time: str | None = Field(default=None)
    total_records_to_process: int | None = Field(default=None)
    records_processed: int = Field(default=0)
    records_created: int = Field(default=0)
    records_updated: int = Field(default=0)
    records_failed: int = Field(default=0)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    dry_run: bool = Field(default=False)
    sync_details: dict[str, Any] = Field(default_factory=dict)


# Employee Search Parameters Model
class EmployeeSearchParams(SQLModel):
    search_query: str | None = Field(default=None, max_length=255)  # Search by name, email, or employee_id
    department: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    office_location: str | None = Field(default=None, max_length=255)
    employment_status: str | None = Field(default=None, regex="^(active|inactive|terminated|all)$")
    employment_type: str | None = Field(default=None, regex="^(full_time|part_time|contractor|all)$")
    has_github_mapping: bool | None = Field(default=None)  # Filter by GitHub mapping status
    manager_employee_id: str | None = Field(default=None, max_length=255)  # Filter by reporting manager
    grade: str | None = Field(default=None, max_length=50)
    business_unit: str | None = Field(default=None, max_length=255)
    date_of_joining_from: str | None = Field(default=None)  # ISO date string
    date_of_joining_to: str | None = Field(default=None)  # ISO date string
    sort_by: str = Field(default="full_name", regex="^(full_name|employee_id|date_of_joining|department|updated_at)$")
    sort_order: str = Field(default="asc", regex="^(asc|desc)$")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    include_custom_attributes: bool = Field(default=False)  # Include custom attributes in response


# Team with Skills Response Model
class TeamWithSkillsResponse(SQLModel):
    team: TeamStructurePublic
    manager: DarwinBoxEmployeePublic | None = Field(default=None)
    team_members: list[DarwinBoxEmployeePublic] = Field(default_factory=list)
    total_members: int = Field(default=0)
    skill_summary: dict[str, Any] = Field(default_factory=dict)  # Aggregated team skills
    skill_distribution: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)  # Skills by category
    skill_gaps: list[dict[str, Any]] = Field(default_factory=list)  # Identified skill gaps
    top_skills: list[dict[str, Any]] = Field(default_factory=list)  # Most common skills in team
    rare_skills: list[dict[str, Any]] = Field(default_factory=list)  # Unique/rare skills in team
    skill_coverage: dict[str, float] = Field(default_factory=dict)  # Percentage coverage by skill category
    recommendations: list[str] = Field(default_factory=list)  # Training/hiring recommendations
    last_analyzed_at: str | None = Field(default=None)


# Batch Mapping Review Models
class MappingReviewItem(SQLModel):
    """Single mapping to review/approve"""
    darwinbox_employee_id: uuid.UUID
    github_username: str
    action: str = Field(regex="^(approve|reject|skip)$")
    notes: str | None = Field(default=None, max_length=500)


class BatchMappingReview(SQLModel):
    """Batch review of multiple mapping suggestions"""
    mappings: list[MappingReviewItem]
    auto_verify: bool = Field(default=True, description="Automatically mark approved mappings as verified")


class BatchMappingReviewResponse(SQLModel):
    """Response from batch mapping review"""
    total_reviewed: int
    approved: int
    rejected: int
    skipped: int
    errors: list[dict[str, str]] = Field(default_factory=list)
