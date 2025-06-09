"""
Scaler CRM API Routes

This module provides API endpoints for:
- CRM authentication and connection management
- Lead and activity data synchronization
- Sales performance analysis
- Conversation transcript analysis and feedback
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlmodel import Session, select, func
from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.core.encryption import encryption_service
from app.models import (
    Message,
    ScalerCRMAuth,
    ScalerCRMAuthConnect,
    ScalerCRMAuthPublic,
    ScalerCRMAuthResponse,
    ScalerLead,
    ScalerLeadPublic,
    ScalerActivity,
    ScalerActivityPublic,
    ScalerConversation,
    ScalerConversationPublic,
    ConversationFeedback,
    ConversationFeedbackPublic,
    SalesPerformanceAnalysis,
    SalesPerformanceAnalysisPublic,
    SalesPerformanceResponse,
    ConversationAnalysisResponse,
    TeamPerformanceResponse,
)
from app.services.scaler_crm_service import scaler_crm_service
from app.services.sales_analysis_service import sales_analysis_service

router = APIRouter()


@router.post("/connect", response_model=ScalerCRMAuthResponse)
async def connect_crm(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    connect_data: ScalerCRMAuthConnect,
) -> Any:
    """
    Connect to Scaler CRM using email and password.
    This will authenticate and store encrypted tokens.
    """
    # Check if user already has a CRM connection
    existing_auth = session.exec(
        select(ScalerCRMAuth).where(ScalerCRMAuth.owner_id == current_user.id)
    ).first()
    
    if existing_auth and existing_auth.is_active:
        return ScalerCRMAuthResponse(
            success=False,
            message="You already have an active CRM connection. Please disconnect first.",
            crm_auth=None
        )
    
    # Authenticate with CRM
    auth_result = await scaler_crm_service.authenticate_with_credentials(
        connect_data.email, connect_data.password
    )
    
    if not auth_result["success"]:
        return ScalerCRMAuthResponse(
            success=False,
            message=auth_result.get("error", "Authentication failed"),
            crm_auth=None
        )
    
    # Create or update CRM auth record
    if existing_auth:
        # Update existing record
        existing_auth.crm_user_email = connect_data.email
        existing_auth.crm_user_id = auth_result.get("user_id")
        existing_auth.crm_user_name = auth_result.get("user_name")
        existing_auth.encrypted_access_token = encryption_service.encrypt(auth_result["access_token"])
        if auth_result.get("refresh_token"):
            existing_auth.encrypted_refresh_token = encryption_service.encrypt(auth_result["refresh_token"])
        existing_auth.token_expires_at = (
            datetime.utcnow() + timedelta(seconds=auth_result.get("expires_in", 3600))
        ).isoformat()
        existing_auth.is_active = True
        existing_auth.updated_at = datetime.utcnow().isoformat()
        session.add(existing_auth)
        session.commit()
        session.refresh(existing_auth)
        crm_auth = existing_auth
    else:
        # Create new record
        crm_auth = ScalerCRMAuth(
            crm_user_email=connect_data.email,
            crm_user_id=auth_result.get("user_id"),
            crm_user_name=auth_result.get("user_name"),
            encrypted_access_token=encryption_service.encrypt(auth_result["access_token"]),
            encrypted_refresh_token=encryption_service.encrypt(auth_result["refresh_token"]) if auth_result.get("refresh_token") else None,
            token_expires_at=(
                datetime.utcnow() + timedelta(seconds=auth_result.get("expires_in", 3600))
            ).isoformat(),
            owner_id=current_user.id
        )
        session.add(crm_auth)
        session.commit()
        session.refresh(crm_auth)
    
    return ScalerCRMAuthResponse(
        success=True,
        message="Successfully connected to Scaler CRM",
        crm_auth=ScalerCRMAuthPublic.model_validate(crm_auth)
    )


@router.get("/status", response_model=ScalerCRMAuthPublic | None)
async def get_crm_status(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Get current CRM connection status"""
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not crm_auth:
        return None
    
    return ScalerCRMAuthPublic.model_validate(crm_auth)


@router.delete("/disconnect", response_model=Message)
async def disconnect_crm(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Disconnect from Scaler CRM"""
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(ScalerCRMAuth.owner_id == current_user.id)
    ).first()
    
    if not crm_auth:
        raise HTTPException(status_code=404, detail="No CRM connection found")
    
    # Soft delete - mark as inactive
    crm_auth.is_active = False
    crm_auth.updated_at = datetime.utcnow().isoformat()
    session.add(crm_auth)
    session.commit()
    
    return Message(message="Successfully disconnected from Scaler CRM")


@router.post("/sync", response_model=Dict[str, Any])
async def sync_crm_data(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    months_to_sync: int = Query(default=12, ge=1, le=24),
) -> Any:
    """
    Sync CRM data for the authenticated user.
    This can be a long-running operation and is executed in the background.
    """
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not crm_auth:
        raise HTTPException(status_code=404, detail="No active CRM connection found")
    
    # Check if sync is already in progress
    if crm_auth.sync_status == "syncing":
        return {
            "status": "in_progress",
            "message": "Sync is already in progress",
            "last_sync": crm_auth.last_sync_at
        }
    
    # Start sync in background
    background_tasks.add_task(
        scaler_crm_service.sync_user_data,
        session,
        current_user,
        crm_auth,
        months_to_sync
    )
    
    return {
        "status": "started",
        "message": f"Started syncing {months_to_sync} months of CRM data",
        "sync_id": crm_auth.id
    }


@router.get("/sync-status", response_model=Dict[str, Any])
async def get_sync_status(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """Get the current sync status"""
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not crm_auth:
        raise HTTPException(status_code=404, detail="No active CRM connection found")
    
    # Get data counts
    lead_count = session.exec(
        select(func.count(ScalerLead.id)).where(ScalerLead.crm_auth_id == crm_auth.id)
    ).first()
    
    activity_count = session.exec(
        select(func.count(ScalerActivity.id)).where(ScalerActivity.crm_auth_id == crm_auth.id)
    ).first()
    
    conversation_count = session.exec(
        select(func.count(ScalerConversation.id)).where(ScalerConversation.crm_auth_id == crm_auth.id)
    ).first()
    
    return {
        "sync_status": crm_auth.sync_status,
        "last_sync_at": crm_auth.last_sync_at,
        "data_counts": {
            "leads": lead_count,
            "activities": activity_count,
            "conversations": conversation_count
        }
    }


@router.get("/leads", response_model=Dict[str, Any])
async def get_leads(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, le=100),
    lead_status: Optional[str] = None,
    lead_stage: Optional[str] = None,
    search: Optional[str] = None,
) -> Any:
    """Get synced leads with optional filters"""
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not crm_auth:
        raise HTTPException(status_code=404, detail="No active CRM connection found")
    
    # Build query
    query = select(ScalerLead).where(ScalerLead.crm_auth_id == crm_auth.id)
    
    if lead_status:
        query = query.where(ScalerLead.lead_status == lead_status)
    if lead_stage:
        query = query.where(ScalerLead.lead_stage == lead_stage)
    if search:
        search_term = f"%{search}%"
        query = query.where(
            (ScalerLead.lead_name.ilike(search_term)) |
            (ScalerLead.email.ilike(search_term)) |
            (ScalerLead.company.ilike(search_term))
        )
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).first()
    
    # Get paginated results
    leads = session.exec(
        query.order_by(ScalerLead.created_date.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    
    # Convert to public models
    lead_publics = []
    for lead in leads:
        lead_public = ScalerLeadPublic.model_validate(lead)
        # Add counts
        lead_public.activity_count = len(lead.activities)
        lead_public.conversation_count = len(lead.conversations)
        lead_publics.append(lead_public)
    
    return {
        "data": lead_publics,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/activities", response_model=Dict[str, Any])
async def get_activities(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
    lead_id: Optional[str] = None,
    activity_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Any:
    """Get synced activities with optional filters"""
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not crm_auth:
        raise HTTPException(status_code=404, detail="No active CRM connection found")
    
    # Build query
    query = select(ScalerActivity).where(ScalerActivity.crm_auth_id == crm_auth.id)
    
    if lead_id:
        # Find lead by lead_id
        lead = session.exec(
            select(ScalerLead).where(
                ScalerLead.lead_id == lead_id,
                ScalerLead.crm_auth_id == crm_auth.id
            )
        ).first()
        if lead:
            query = query.where(ScalerActivity.lead_id == lead.id)
    
    if activity_type:
        query = query.where(ScalerActivity.activity_type == activity_type)
    if start_date:
        query = query.where(ScalerActivity.activity_date >= start_date.isoformat())
    if end_date:
        query = query.where(ScalerActivity.activity_date <= end_date.isoformat())
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).first()
    
    # Get paginated results
    activities = session.exec(
        query.order_by(ScalerActivity.activity_date.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    
    # Convert to public models with lead info
    activity_publics = []
    for activity in activities:
        activity_public = ScalerActivityPublic.model_validate(activity)
        if activity.lead:
            activity_public.lead_name = activity.lead.lead_name
        activity_publics.append(activity_public)
    
    return {
        "data": activity_publics,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.get("/conversations", response_model=Dict[str, Any])
async def get_conversations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, le=100),
    lead_id: Optional[str] = None,
    conversation_type: Optional[str] = None,
    has_transcript: Optional[bool] = None,
    analysis_status: Optional[str] = None,
) -> Any:
    """Get synced conversations with optional filters"""
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not crm_auth:
        raise HTTPException(status_code=404, detail="No active CRM connection found")
    
    # Build query
    query = select(ScalerConversation).where(ScalerConversation.crm_auth_id == crm_auth.id)
    
    if lead_id:
        # Find lead by lead_id
        lead = session.exec(
            select(ScalerLead).where(
                ScalerLead.lead_id == lead_id,
                ScalerLead.crm_auth_id == crm_auth.id
            )
        ).first()
        if lead:
            query = query.where(ScalerConversation.lead_id == lead.id)
    
    if conversation_type:
        query = query.where(ScalerConversation.conversation_type == conversation_type)
    if has_transcript is not None:
        query = query.where(ScalerConversation.transcript_available == has_transcript)
    if analysis_status:
        query = query.where(ScalerConversation.analysis_status == analysis_status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = session.exec(count_query).first()
    
    # Get paginated results
    conversations = session.exec(
        query.order_by(ScalerConversation.conversation_date.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    
    # Convert to public models
    conversation_publics = []
    for conv in conversations:
        conv_public = ScalerConversationPublic.model_validate(conv)
        conv_public.has_feedback = len(conv.feedback_items) > 0
        conv_public.feedback_count = len(conv.feedback_items)
        conversation_publics.append(conv_public)
    
    return {
        "data": conversation_publics,
        "total": total,
        "skip": skip,
        "limit": limit
    }


@router.post("/analyze-performance", response_model=SalesPerformanceResponse)
async def analyze_sales_performance(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    period_months: int = Query(default=3, ge=1, le=12),
) -> Any:
    """
    Analyze sales performance and generate skill ratings.
    This uses LLM to analyze activities and provide insights.
    """
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not crm_auth:
        raise HTTPException(status_code=404, detail="No active CRM connection found")
    
    # Check if we have enough data
    activity_count = session.exec(
        select(func.count(ScalerActivity.id)).where(ScalerActivity.crm_auth_id == crm_auth.id)
    ).first()
    
    if activity_count < 10:
        raise HTTPException(
            status_code=400,
            detail="Not enough activity data for analysis. Please sync more data."
        )
    
    # Perform analysis
    try:
        analysis = await sales_analysis_service.analyze_sales_performance(
            session, crm_auth, period_months
        )
        
        # Get recent conversations
        recent_conversations = session.exec(
            select(ScalerConversation)
            .where(ScalerConversation.crm_auth_id == crm_auth.id)
            .order_by(ScalerConversation.conversation_date.desc())
            .limit(10)
        ).all()
        
        # Calculate activity trends
        end_date = datetime.utcnow()
        activity_trends = {}
        for i in range(period_months):
            month_start = end_date - timedelta(days=(i+1)*30)
            month_end = end_date - timedelta(days=i*30)
            
            month_activities = session.exec(
                select(func.count(ScalerActivity.id)).where(
                    ScalerActivity.crm_auth_id == crm_auth.id,
                    ScalerActivity.activity_date >= month_start.isoformat(),
                    ScalerActivity.activity_date < month_end.isoformat()
                )
            ).first()
            
            month_key = month_end.strftime("%Y-%m")
            activity_trends[month_key] = month_activities
        
        # Generate learning recommendations based on skill ratings
        learning_recs = []
        for rating in analysis.skill_ratings:
            if rating.inferred_level < 3:
                learning_recs.append(f"Focus on improving {rating.skill_name}: {rating.improvement_suggestions}")
        
        return SalesPerformanceResponse(
            current_performance=SalesPerformanceAnalysisPublic.model_validate(analysis),
            skill_ratings=[SalesSkillRatingPublic.model_validate(r) for r in analysis.skill_ratings],
            recent_conversations=[ScalerConversationPublic.model_validate(c) for c in recent_conversations],
            activity_trends=activity_trends,
            learning_recommendations=learning_recs[:5]  # Top 5 recommendations
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/conversations/{conversation_id}/analyze", response_model=ConversationAnalysisResponse)
async def analyze_conversation(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    conversation_id: str,
) -> Any:
    """
    Analyze a specific conversation and generate feedback.
    This uses LLM to analyze the transcript and provide constructive feedback.
    """
    crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not crm_auth:
        raise HTTPException(status_code=404, detail="No active CRM connection found")
    
    # Get conversation
    conversation = session.exec(
        select(ScalerConversation).where(
            ScalerConversation.id == conversation_id,
            ScalerConversation.crm_auth_id == crm_auth.id
        )
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    if not conversation.transcript_available:
        raise HTTPException(status_code=400, detail="No transcript available for this conversation")
    
    # Analyze conversation
    try:
        feedback_items = await sales_analysis_service.analyze_conversation(
            session, conversation
        )
        
        # Prepare response
        key_moments = []
        skill_demonstrations = []
        next_steps = []
        
        for feedback in feedback_items:
            if feedback.feedback_type == "strength":
                skill_demonstrations.append({
                    "skill": feedback.feedback_category,
                    "description": feedback.feedback_text,
                    "moment": feedback.specific_moment
                })
            elif feedback.specific_moment:
                key_moments.append({
                    "type": feedback.feedback_type,
                    "moment": feedback.specific_moment,
                    "feedback": feedback.feedback_text
                })
            if feedback.suggested_response:
                next_steps.append(feedback.suggested_response)
        
        overall_assessment = f"Conversation analyzed with {len(feedback_items)} feedback points generated."
        if conversation.transcript_summary:
            overall_assessment = conversation.transcript_summary
        
        return ConversationAnalysisResponse(
            conversation=ScalerConversationPublic.model_validate(conversation),
            feedback_items=[ConversationFeedbackPublic.model_validate(f) for f in feedback_items],
            overall_assessment=overall_assessment,
            key_moments=key_moments[:5],  # Top 5 moments
            skill_demonstrations=skill_demonstrations[:5],  # Top 5 demonstrations
            next_steps=next_steps[:3]  # Top 3 next steps
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/team-performance", response_model=TeamPerformanceResponse)
async def get_team_performance(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    team_id: Optional[str] = None,
) -> Any:
    """
    Get team performance metrics (for managers).
    This is a placeholder for future team analytics features.
    """
    # For now, return mock data structure
    # In a real implementation, this would aggregate data across team members
    return TeamPerformanceResponse(
        team_members=[],
        aggregate_metrics={
            "total_leads": 0,
            "total_activities": 0,
            "average_conversion_rate": 0,
            "team_size": 0
        },
        top_performers=[],
        team_strengths=["Team performance analysis coming soon"],
        team_improvement_areas=["Connect team members to analyze performance"],
        collaboration_score=0.0
    )