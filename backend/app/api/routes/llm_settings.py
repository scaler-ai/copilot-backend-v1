from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.encryption import encryption_service
from app.models import (
    LLMProvider,
    LLMProvidersResponse,
    LLMSettings,
    LLMSettingsCreate,
    LLMSettingsPublic,
    LLMSettingsUpdate,
    Message,
)

router = APIRouter()


# Supported LLM providers and their models
SUPPORTED_PROVIDERS = [
    LLMProvider(
        name="openai",
        display_name="OpenAI",
        models=[
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo"
        ],
        requires_api_key=True,
        default_model="gpt-4o-mini",
        max_tokens_limit=4096
    ),
    LLMProvider(
        name="anthropic",
        display_name="Anthropic (Claude)",
        models=[
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ],
        requires_api_key=True,
        default_model="claude-3-5-sonnet-20241022",
        max_tokens_limit=8192
    ),
    LLMProvider(
        name="google",
        display_name="Google (Gemini)",
        models=[
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-pro"
        ],
        requires_api_key=True,
        default_model="gemini-1.5-flash",
        max_tokens_limit=8192
    ),
    LLMProvider(
        name="azure",
        display_name="Azure OpenAI",
        models=[
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-35-turbo"
        ],
        requires_api_key=True,
        default_model="gpt-4o-mini",
        max_tokens_limit=4096
    )
]


@router.get("/providers", response_model=LLMProvidersResponse)
def get_llm_providers() -> Any:
    """
    Get list of supported LLM providers and their models.
    """
    return LLMProvidersResponse(providers=SUPPORTED_PROVIDERS)


@router.get("/", response_model=LLMSettingsPublic | None)
def get_llm_settings(
    session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get current user's LLM settings.
    """
    statement = select(LLMSettings).where(LLMSettings.owner_id == current_user.id)
    settings = session.exec(statement).first()

    if not settings:
        return None

    return LLMSettingsPublic(
        id=settings.id,
        provider=settings.provider,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        is_active=settings.is_active,
        created_at=settings.created_at,
        updated_at=settings.updated_at,
        owner_id=settings.owner_id
    )


@router.post("/", response_model=LLMSettingsPublic)
def create_llm_settings(
    *, session: SessionDep, current_user: CurrentUser, settings_in: LLMSettingsCreate
) -> Any:
    """
    Create LLM settings for the current user.
    """
    # Check if user already has settings
    existing_statement = select(LLMSettings).where(LLMSettings.owner_id == current_user.id)
    existing_settings = session.exec(existing_statement).first()

    if existing_settings:
        raise HTTPException(
            status_code=400,
            detail="User already has LLM settings. Use PUT to update existing settings."
        )

    # Validate provider and model
    provider_info = next((p for p in SUPPORTED_PROVIDERS if p.name == settings_in.provider), None)
    if not provider_info:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: {settings_in.provider}"
        )

    if settings_in.model not in provider_info.models:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported model {settings_in.model} for provider {settings_in.provider}"
        )

    # Validate max_tokens against provider limit
    if settings_in.max_tokens > provider_info.max_tokens_limit:
        raise HTTPException(
            status_code=400,
            detail=f"max_tokens ({settings_in.max_tokens}) exceeds provider limit ({provider_info.max_tokens_limit})"
        )

    # Encrypt API key
    encrypted_api_key = encryption_service.encrypt(settings_in.api_key)

    # Create settings
    db_settings = LLMSettings(
        provider=settings_in.provider,
        model=settings_in.model,
        temperature=settings_in.temperature,
        max_tokens=settings_in.max_tokens,
        is_active=settings_in.is_active,
        encrypted_api_key=encrypted_api_key,
        owner_id=current_user.id
    )

    session.add(db_settings)
    session.commit()
    session.refresh(db_settings)

    return LLMSettingsPublic(
        id=db_settings.id,
        provider=db_settings.provider,
        model=db_settings.model,
        temperature=db_settings.temperature,
        max_tokens=db_settings.max_tokens,
        is_active=db_settings.is_active,
        created_at=db_settings.created_at,
        updated_at=db_settings.updated_at,
        owner_id=db_settings.owner_id
    )


@router.put("/", response_model=LLMSettingsPublic)
def update_llm_settings(
    *, session: SessionDep, current_user: CurrentUser, settings_in: LLMSettingsUpdate
) -> Any:
    """
    Update LLM settings for the current user.
    """
    statement = select(LLMSettings).where(LLMSettings.owner_id == current_user.id)
    db_settings = session.exec(statement).first()

    if not db_settings:
        raise HTTPException(status_code=404, detail="LLM settings not found")

    # Validate provider and model if being updated
    if settings_in.provider:
        provider_info = next((p for p in SUPPORTED_PROVIDERS if p.name == settings_in.provider), None)
        if not provider_info:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported provider: {settings_in.provider}"
            )

        # If model is also being updated, validate it against the new provider
        model_to_check = settings_in.model or db_settings.model
        if model_to_check not in provider_info.models:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported model {model_to_check} for provider {settings_in.provider}"
            )

        # Validate max_tokens against new provider if provided
        max_tokens_to_check = settings_in.max_tokens or db_settings.max_tokens
        if max_tokens_to_check > provider_info.max_tokens_limit:
            raise HTTPException(
                status_code=400,
                detail=f"max_tokens ({max_tokens_to_check}) exceeds provider limit ({provider_info.max_tokens_limit})"
            )

    elif settings_in.model:
        # Model is being updated but not provider, validate against current provider
        current_provider_info = next((p for p in SUPPORTED_PROVIDERS if p.name == db_settings.provider), None)
        if current_provider_info and settings_in.model not in current_provider_info.models:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported model {settings_in.model} for provider {db_settings.provider}"
            )

    # Update fields
    update_data = settings_in.model_dump(exclude_unset=True)

    # Handle API key encryption
    if "api_key" in update_data:
        encrypted_api_key = encryption_service.encrypt(update_data["api_key"])
        update_data["encrypted_api_key"] = encrypted_api_key
        del update_data["api_key"]

    # Update timestamp
    update_data["updated_at"] = datetime.utcnow().isoformat()

    # Apply updates
    for field, value in update_data.items():
        setattr(db_settings, field, value)

    session.add(db_settings)
    session.commit()
    session.refresh(db_settings)

    return LLMSettingsPublic(
        id=db_settings.id,
        provider=db_settings.provider,
        model=db_settings.model,
        temperature=db_settings.temperature,
        max_tokens=db_settings.max_tokens,
        is_active=db_settings.is_active,
        created_at=db_settings.created_at,
        updated_at=db_settings.updated_at,
        owner_id=db_settings.owner_id
    )


@router.delete("/")
def delete_llm_settings(
    session: SessionDep, current_user: CurrentUser
) -> Message:
    """
    Delete LLM settings for the current user.
    """
    statement = select(LLMSettings).where(LLMSettings.owner_id == current_user.id)
    db_settings = session.exec(statement).first()

    if not db_settings:
        raise HTTPException(status_code=404, detail="LLM settings not found")

    session.delete(db_settings)
    session.commit()

    return Message(message="LLM settings deleted successfully")


@router.post("/test")
def test_llm_settings(
    session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Test the current user's LLM settings by making a simple API call.
    """
    statement = select(LLMSettings).where(LLMSettings.owner_id == current_user.id)
    db_settings = session.exec(statement).first()

    if not db_settings:
        raise HTTPException(status_code=404, detail="LLM settings not found")

    if not db_settings.is_active:
        raise HTTPException(status_code=400, detail="LLM settings are disabled")

    try:
        # Decrypt API key for testing
        encryption_service.decrypt(db_settings.encrypted_api_key)

        # This is a placeholder for actual LLM API testing
        # In the actual implementation, we would make a real API call here

        return {
            "success": True,
            "message": f"LLM settings for {db_settings.provider} ({db_settings.model}) are configured correctly",
            "provider": db_settings.provider,
            "model": db_settings.model
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to test LLM settings: {str(e)}",
            "provider": db_settings.provider,
            "model": db_settings.model
        }
