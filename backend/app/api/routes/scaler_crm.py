"""
Scaler CRM API Routes

This module provides API endpoints for:
- CRM authentication and connection management
- Lead and activity data synchronization
- Sales performance analysis
- Conversation transcript analysis and feedback
"""

import logging
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
    SalesSkillRating,
    SalesSkillRatingPublic,
    SalesPerformanceResponse,
    ConversationAnalysisResponse,
    TeamPerformanceResponse,
)
from app.services.scaler_crm_service import scaler_crm_service
from app.services.sales_analysis_service import sales_analysis_service
from app.core.db import engine

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
    
    # Update sync status to syncing
    crm_auth.sync_status = "syncing"
    session.add(crm_auth)
    session.commit()
    
    # Create a background task wrapper that creates its own session
    async def sync_with_new_session():
        from sqlmodel import Session as NewSession
        with NewSession(engine) as new_session:
            # Re-fetch the CRM auth in the new session
            fresh_crm_auth = new_session.get(ScalerCRMAuth, crm_auth.id)
            if fresh_crm_auth:
                await scaler_crm_service.sync_user_data(
                    new_session,
                    current_user,
                    fresh_crm_auth,
                    months_to_sync
                )
    
    # Start sync in background
    background_tasks.add_task(sync_with_new_session)
    
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
    
    if not activity_count or activity_count < 10:
        raise HTTPException(
            status_code=400,
            detail="Not enough activity data for analysis. Please sync more data."
        )
    
    # Perform analysis
    try:
        # Get activities for enhanced analysis
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=period_months * 30)
        
        activities = session.exec(
            select(ScalerActivity).where(
                ScalerActivity.crm_auth_id == crm_auth.id,
                ScalerActivity.activity_date >= start_date.isoformat(),
                ScalerActivity.activity_date <= end_date.isoformat()
            )
        ).all()
        
        # Get enhanced activity analysis
        activity_summary = sales_analysis_service._prepare_activity_summary(activities)
        
        # Perform performance analysis
        analysis = await sales_analysis_service.analyze_sales_performance(
            session, current_user, crm_auth, period_months
        )
        
        # Get recent conversations
        recent_conversations = session.exec(
            select(ScalerConversation)
            .where(ScalerConversation.crm_auth_id == crm_auth.id)
            .order_by(ScalerConversation.conversation_date.desc())
            .limit(10)
        ).all()
        
        # Calculate activity trends
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
        
        # Create enhanced performance data by combining database analysis with activity insights
        performance_dict = analysis.model_dump()
        
        # Add enhanced fields from activity analysis
        performance_dict.update({
            "behavioral_insights": activity_summary.get("behavioral_insights", []),
            "follow_up_analysis": activity_summary.get("follow_up_analysis", {}),
            "timing_patterns": activity_summary.get("timing_patterns", {}),
            "common_sequences": activity_summary.get("common_sequences", {}),
        })
        
        # Parse the LLM analysis from the performance summary to add more enhanced fields
        try:
            # The strengths_identified and improvement_areas are JSON fields
            if hasattr(analysis.strengths_identified, '__iter__') and not isinstance(analysis.strengths_identified, str):
                performance_dict["behavioral_strengths"] = list(analysis.strengths_identified)
                performance_dict["success_patterns"] = list(analysis.strengths_identified)  # For backwards compatibility
            else:
                performance_dict["behavioral_strengths"] = []
                performance_dict["success_patterns"] = []
                
            if hasattr(analysis.improvement_areas, '__iter__') and not isinstance(analysis.improvement_areas, str):
                # Convert simple list to detailed opportunities format for backwards compatibility
                improvement_opportunities = []
                for area in analysis.improvement_areas:
                    if isinstance(area, dict):
                        improvement_opportunities.append(area)
                    else:
                        improvement_opportunities.append({
                            "area": str(area),
                            "current_behavior": "Current approach needs improvement",
                            "recommended_action": f"Focus on developing {area}",
                            "expected_impact": "Improved sales effectiveness",
                            "implementation_tip": "Start with small, consistent changes"
                        })
                performance_dict["improvement_opportunities"] = improvement_opportunities
            else:
                performance_dict["improvement_opportunities"] = []
                
            # Add additional enhanced fields for the UI
            performance_dict.update({
                "time_management_insights": [
                    "Based on your activity patterns and response times",
                    f"Average response time: {analysis.average_response_time_hours or 'N/A'} hours"
                ] if analysis.average_response_time_hours else [],
                "next_30_days_action_plan": [
                    {
                        "week": 1,
                        "focus_area": "Activity Optimization",
                        "specific_actions": ["Increase daily outreach", "Follow up more consistently"],
                        "success_metrics": "20% increase in activities per week"
                    },
                    {
                        "week": 2,
                        "focus_area": "Response Time Improvement", 
                        "specific_actions": ["Set reminders for follow-ups", "Check CRM twice daily"],
                        "success_metrics": "Reduce average response time by 25%"
                    },
                    {
                        "week": 3,
                        "focus_area": "Conversion Rate Focus",
                        "specific_actions": ["Analyze successful deals", "Improve discovery calls"],
                        "success_metrics": "Improve conversion rate by 5%"
                    },
                    {
                        "week": 4,
                        "focus_area": "Process Refinement",
                        "specific_actions": ["Document best practices", "Review and adjust approach"],
                        "success_metrics": "Maintain consistent improvement trends"
                    }
                ],
                "performance_rating": {
                    "overall_score": min(10, max(1, int((analysis.conversion_rate / 10) + 5))),
                    "explanation": f"Based on {analysis.conversion_rate}% conversion rate and {analysis.total_activities} activities",
                    "potential_ceiling": "8-9"
                }
            })
                
        except Exception as e:
            logging.warning(f"Error parsing LLM analysis fields: {e}")
            performance_dict["behavioral_strengths"] = []
            performance_dict["improvement_opportunities"] = []
            performance_dict["success_patterns"] = []
            performance_dict["time_management_insights"] = []
            performance_dict["next_30_days_action_plan"] = []
            performance_dict["performance_rating"] = {"overall_score": 5, "explanation": "Basic analysis", "potential_ceiling": "7"}
        
        return SalesPerformanceResponse(
            current_performance=performance_dict,
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


@router.get("/team-performance")
async def get_team_performance(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    team_id: Optional[str] = None,
    period_months: int = Query(default=3, ge=1, le=12),
) -> Any:
    """
    Get team performance metrics for managers.
    This analyzes the sales performance of all team members.
    """
    try:
        # Get team performance data
        team_data = await sales_analysis_service.analyze_team_performance(
            session=session,
            current_user=current_user,
            period_months=period_months
        )
        
        return team_data
        
    except HTTPException as e:
        raise e
    except Exception as e:
        logging.error(f"Error getting team performance: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get team performance: {str(e)}"
        )


@router.get("/manager-info", response_model=Dict[str, Any])
async def get_manager_info(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    """
    Get manager information and team members.
    Returns whether the user is a manager and their team members if applicable.
    """
    from app.models import DarwinBoxEmployee
    
    # Get current user's employee record
    employee = session.exec(
        select(DarwinBoxEmployee).where(DarwinBoxEmployee.email == current_user.email)
    ).first()
    
    if not employee:
        return {
            "is_manager": False,
            "employee_info": None,
            "team_members": []
        }
    
    # Get team members if user is a manager
    team_members = []
    if employee.is_manager:
        team = session.exec(
            select(DarwinBoxEmployee).where(
                DarwinBoxEmployee.reporting_manager_id == employee.darwinbox_id,
                DarwinBoxEmployee.employment_status == "active"
            ).order_by(DarwinBoxEmployee.full_name)
        ).all()
        
        # Check CRM sync status for each team member
        team_members = []
        for member in team:
            # Get user account
            member_user = session.exec(
                select(User).where(User.email == member.email)
            ).first()
            
            member_info = {
                "id": str(member.id),
                "darwinbox_id": member.darwinbox_id,
                "full_name": member.full_name,
                "email": member.email,
                "designation": member.designation,
                "department": member.department,
                "has_user_account": member_user is not None,
                "crm_sync_status": None,
                "last_sync_at": None
            }
            
            if member_user:
                # Check CRM sync status
                member_crm = session.exec(
                    select(ScalerCRMAuth).where(
                        ScalerCRMAuth.owner_id == member_user.id,
                        ScalerCRMAuth.is_active == True
                    )
                ).first()
                
                if member_crm:
                    member_info["crm_sync_status"] = member_crm.sync_status
                    member_info["last_sync_at"] = member_crm.last_sync_at
            
            team_members.append(member_info)
    
    return {
        "is_manager": employee.is_manager,
        "employee_info": {
            "id": str(employee.id),
            "full_name": employee.full_name,
            "email": employee.email,
            "designation": employee.designation,
            "department": employee.department
        },
        "team_members": team_members
    }


@router.post("/sync-team-member", response_model=Dict[str, Any])
async def sync_team_member_data(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    member_email: str,
    months_to_sync: int = Query(default=3, ge=1, le=12),
) -> Any:
    """
    Sync a team member's CRM data using the manager's authentication.
    Only available for managers to sync their team members' data.
    """
    from app.models import DarwinBoxEmployee, User
    
    # Verify current user is a manager
    manager_employee = session.exec(
        select(DarwinBoxEmployee).where(DarwinBoxEmployee.email == current_user.email)
    ).first()
    
    if not manager_employee or not manager_employee.is_manager:
        raise HTTPException(status_code=403, detail="This feature is only available for managers")
    
    # Verify the requested member reports to this manager
    member_employee = session.exec(
        select(DarwinBoxEmployee).where(
            DarwinBoxEmployee.email == member_email,
            DarwinBoxEmployee.reporting_manager_id == manager_employee.darwinbox_id
        )
    ).first()
    
    if not member_employee:
        raise HTTPException(
            status_code=404, 
            detail=f"Team member {member_email} not found or doesn't report to you"
        )
    
    # Get manager's CRM auth
    manager_crm_auth = session.exec(
        select(ScalerCRMAuth).where(
            ScalerCRMAuth.owner_id == current_user.id,
            ScalerCRMAuth.is_active == True
        )
    ).first()
    
    if not manager_crm_auth:
        raise HTTPException(
            status_code=400,
            detail="Manager must have an active CRM connection to sync team member data"
        )
    
    # Get or create member's user account
    member_user = session.exec(
        select(User).where(User.email == member_email)
    ).first()
    
    if not member_user:
        # Create user account for team member
        member_user = User(
            email=member_email,
            full_name=member_employee.full_name,
            is_active=True
        )
        session.add(member_user)
        session.commit()
        session.refresh(member_user)
    
    # Get or create member's CRM auth record
    member_crm_auth = session.exec(
        select(ScalerCRMAuth).where(ScalerCRMAuth.owner_id == member_user.id)
    ).first()
    
    if not member_crm_auth:
        # Create CRM auth record for member (using manager's tokens)
        member_crm_auth = ScalerCRMAuth(
            owner_id=member_user.id,
            crm_user_email=member_email,
            crm_user_name=member_employee.full_name,
            # Note: Using manager's encrypted tokens
            encrypted_access_token=manager_crm_auth.encrypted_access_token,
            encrypted_refresh_token=manager_crm_auth.encrypted_refresh_token,
            token_expires_at=manager_crm_auth.token_expires_at,
            sync_status="pending",
            created_at=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow().isoformat()
        )
        session.add(member_crm_auth)
        session.commit()
        session.refresh(member_crm_auth)
    
    # Check if sync is already in progress
    if member_crm_auth.sync_status == "syncing":
        return {
            "status": "in_progress",
            "message": f"Sync already in progress for {member_employee.full_name}",
            "last_sync": member_crm_auth.last_sync_at
        }
    
    # Update sync status
    member_crm_auth.sync_status = "syncing"
    session.add(member_crm_auth)
    session.commit()
    
    # Create background task to sync member's data
    async def sync_member_with_manager_auth():
        from sqlmodel import Session as NewSession
        with NewSession(engine) as new_session:
            # Re-fetch records in new session
            fresh_member_crm = new_session.get(ScalerCRMAuth, member_crm_auth.id)
            fresh_manager_crm = new_session.get(ScalerCRMAuth, manager_crm_auth.id)
            fresh_member_user = new_session.get(User, member_user.id)
            
            if fresh_member_crm and fresh_manager_crm and fresh_member_user:
                # Use custom sync method that filters by team member's name/email
                await scaler_crm_service.sync_team_member_data(
                    session=new_session,
                    member_user=fresh_member_user,
                    member_crm_auth=fresh_member_crm,
                    manager_crm_auth=fresh_manager_crm,
                    member_email=member_email,
                    months_to_sync=months_to_sync
                )
    
    # Start sync in background
    background_tasks.add_task(sync_member_with_manager_auth)
    
    return {
        "status": "started",
        "message": f"Started syncing {member_employee.full_name}'s CRM data for {months_to_sync} months",
        "member_email": member_email,
        "sync_id": str(member_crm_auth.id)
    }