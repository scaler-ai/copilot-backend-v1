"""
Scaler CRM Service

This service handles all interactions with the Scaler Sales CRM API, including:
- Authentication and token management
- Lead data synchronization
- Activity tracking and analysis
- Conversation transcript retrieval
- Sales performance metrics calculation
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import httpx
from sqlmodel import Session, select, func
from app.core.config import settings
from app.core.encryption import encryption_service
from app.models import (
    User,
    ScalerCRMAuth,
    ScalerLead,
    ScalerActivity,
    ScalerConversation,
    SalesPerformanceAnalysis,
    SalesSkillRating,
    ConversationFeedback
)

logger = logging.getLogger(__name__)


class ScalerCRMService:
    """Service for interacting with Scaler Sales CRM API"""
    
    def __init__(self):
        self.base_url = settings.SCALER_CRM_API_URL if hasattr(settings, 'SCALER_CRM_API_URL') else "https://api.scalercrm.com/v1"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def authenticate_with_credentials(
        self, 
        email: str, 
        password: str
    ) -> Dict[str, Any]:
        """
        Authenticate with Scaler CRM using email and password.
        Returns access token and user information.
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/auth/login",
                json={
                    "email": email,
                    "password": password
                }
            )
            response.raise_for_status()
            
            data = response.json()
            return {
                "success": True,
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "expires_in": data.get("expires_in", 3600),
                "user_id": data.get("user_id"),
                "user_name": data.get("user_name")
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"CRM authentication failed: {e.response.status_code}")
            if e.response.status_code == 401:
                return {"success": False, "error": "Invalid credentials"}
            return {"success": False, "error": f"Authentication failed: {str(e)}"}
        except Exception as e:
            logger.error(f"CRM authentication error: {str(e)}")
            return {"success": False, "error": f"Connection error: {str(e)}"}
    
    async def refresh_access_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Refresh access token using refresh token"""
        try:
            response = await self.client.post(
                f"{self.base_url}/auth/refresh",
                json={"refresh_token": refresh_token}
            )
            response.raise_for_status()
            
            data = response.json()
            return {
                "access_token": data.get("access_token"),
                "expires_in": data.get("expires_in", 3600)
            }
        except Exception as e:
            logger.error(f"Token refresh failed: {str(e)}")
            return None
    
    def _get_auth_headers(self, access_token: str) -> Dict[str, str]:
        """Get authorization headers for API requests"""
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    async def get_leads(
        self, 
        access_token: str,
        page: int = 1,
        per_page: int = 100,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Fetch leads from CRM with pagination and filters"""
        try:
            params = {
                "page": page,
                "per_page": per_page
            }
            if filters:
                params.update(filters)
            
            response = await self.client.get(
                f"{self.base_url}/leads",
                headers=self._get_auth_headers(access_token),
                params=params
            )
            response.raise_for_status()
            
            return response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch leads: {e.response.status_code}")
            return {"error": str(e), "leads": []}
        except Exception as e:
            logger.error(f"Error fetching leads: {str(e)}")
            return {"error": str(e), "leads": []}
    
    async def get_activities(
        self,
        access_token: str,
        lead_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        per_page: int = 100
    ) -> Dict[str, Any]:
        """Fetch activities from CRM with optional filters"""
        try:
            params = {
                "page": page,
                "per_page": per_page
            }
            
            if lead_id:
                params["lead_id"] = lead_id
            if start_date:
                params["start_date"] = start_date.isoformat()
            if end_date:
                params["end_date"] = end_date.isoformat()
            
            response = await self.client.get(
                f"{self.base_url}/activities",
                headers=self._get_auth_headers(access_token),
                params=params
            )
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error fetching activities: {str(e)}")
            return {"error": str(e), "activities": []}
    
    async def get_conversations(
        self,
        access_token: str,
        lead_id: Optional[str] = None,
        conversation_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        page: int = 1,
        per_page: int = 100
    ) -> Dict[str, Any]:
        """Fetch conversations from CRM"""
        try:
            params = {
                "page": page,
                "per_page": per_page,
                "include_transcript": True
            }
            
            if lead_id:
                params["lead_id"] = lead_id
            if conversation_type:
                params["type"] = conversation_type
            if start_date:
                params["start_date"] = start_date.isoformat()
            if end_date:
                params["end_date"] = end_date.isoformat()
            
            response = await self.client.get(
                f"{self.base_url}/conversations",
                headers=self._get_auth_headers(access_token),
                params=params
            )
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error fetching conversations: {str(e)}")
            return {"error": str(e), "conversations": []}
    
    async def get_conversation_transcript(
        self,
        access_token: str,
        conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch detailed conversation transcript"""
        try:
            response = await self.client.get(
                f"{self.base_url}/conversations/{conversation_id}/transcript",
                headers=self._get_auth_headers(access_token)
            )
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error fetching transcript: {str(e)}")
            return None
    
    async def sync_user_data(
        self,
        session: Session,
        user: User,
        crm_auth: ScalerCRMAuth,
        months_to_sync: int = 12
    ) -> Dict[str, Any]:
        """Sync all CRM data for a user"""
        try:
            # Decrypt access token
            access_token = encryption_service.decrypt(crm_auth.encrypted_access_token)
            
            # Check if token needs refresh
            if crm_auth.token_expires_at:
                expires_at = datetime.fromisoformat(crm_auth.token_expires_at)
                if expires_at <= datetime.utcnow() + timedelta(minutes=5):
                    # Refresh token
                    if crm_auth.encrypted_refresh_token:
                        refresh_token = encryption_service.decrypt(crm_auth.encrypted_refresh_token)
                        new_tokens = await self.refresh_access_token(refresh_token)
                        if new_tokens:
                            access_token = new_tokens["access_token"]
                            crm_auth.encrypted_access_token = encryption_service.encrypt(access_token)
                            crm_auth.token_expires_at = (
                                datetime.utcnow() + timedelta(seconds=new_tokens["expires_in"])
                            ).isoformat()
                            session.add(crm_auth)
            
            # Update sync status
            crm_auth.sync_status = "syncing"
            crm_auth.updated_at = datetime.utcnow().isoformat()
            session.add(crm_auth)
            session.commit()
            
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=months_to_sync * 30)
            
            # Sync leads
            leads_synced = await self._sync_leads(session, crm_auth, access_token)
            
            # Sync activities
            activities_synced = await self._sync_activities(
                session, crm_auth, access_token, start_date, end_date
            )
            
            # Sync conversations
            conversations_synced = await self._sync_conversations(
                session, crm_auth, access_token, start_date, end_date
            )
            
            # Update sync status
            crm_auth.sync_status = "completed"
            crm_auth.last_sync_at = datetime.utcnow().isoformat()
            session.add(crm_auth)
            session.commit()
            
            return {
                "success": True,
                "leads_synced": leads_synced,
                "activities_synced": activities_synced,
                "conversations_synced": conversations_synced,
                "sync_date": crm_auth.last_sync_at
            }
            
        except Exception as e:
            logger.error(f"Sync failed: {str(e)}")
            crm_auth.sync_status = "failed"
            session.add(crm_auth)
            session.commit()
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _sync_leads(
        self,
        session: Session,
        crm_auth: ScalerCRMAuth,
        access_token: str
    ) -> int:
        """Sync leads from CRM"""
        leads_synced = 0
        page = 1
        
        while True:
            result = await self.get_leads(access_token, page=page)
            if "error" in result or not result.get("leads"):
                break
            
            for lead_data in result["leads"]:
                # Check if lead exists
                existing_lead = session.exec(
                    select(ScalerLead).where(
                        ScalerLead.lead_id == lead_data["id"],
                        ScalerLead.crm_auth_id == crm_auth.id
                    )
                ).first()
                
                if existing_lead:
                    # Update existing lead
                    for field in ["lead_name", "email", "phone", "company", "designation",
                                 "lead_source", "lead_status", "lead_stage", "lead_score",
                                 "last_activity_date", "assigned_to", "assigned_to_id"]:
                        if field in lead_data:
                            setattr(existing_lead, field, lead_data[field])
                    existing_lead.updated_at = datetime.utcnow().isoformat()
                    existing_lead.raw_data = lead_data
                    session.add(existing_lead)
                else:
                    # Create new lead
                    new_lead = ScalerLead(
                        lead_id=lead_data["id"],
                        lead_name=lead_data.get("name", ""),
                        email=lead_data.get("email"),
                        phone=lead_data.get("phone"),
                        company=lead_data.get("company"),
                        designation=lead_data.get("designation"),
                        lead_source=lead_data.get("source"),
                        lead_status=lead_data.get("status", "new"),
                        lead_stage=lead_data.get("stage"),
                        lead_score=lead_data.get("score"),
                        created_date=lead_data.get("created_at"),
                        last_activity_date=lead_data.get("last_activity_at"),
                        assigned_to=lead_data.get("assigned_to_name"),
                        assigned_to_id=lead_data.get("assigned_to_id"),
                        raw_data=lead_data,
                        crm_auth_id=crm_auth.id
                    )
                    session.add(new_lead)
                
                leads_synced += 1
            
            # Check if there are more pages
            if len(result["leads"]) < 100:
                break
            page += 1
        
        session.commit()
        return leads_synced
    
    async def _sync_activities(
        self,
        session: Session,
        crm_auth: ScalerCRMAuth,
        access_token: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """Sync activities from CRM"""
        activities_synced = 0
        page = 1
        
        # Get lead mapping
        lead_map = {}
        leads = session.exec(
            select(ScalerLead).where(ScalerLead.crm_auth_id == crm_auth.id)
        ).all()
        for lead in leads:
            lead_map[lead.lead_id] = lead.id
        
        while True:
            result = await self.get_activities(
                access_token, 
                start_date=start_date,
                end_date=end_date,
                page=page
            )
            if "error" in result or not result.get("activities"):
                break
            
            for activity_data in result["activities"]:
                # Check if activity exists
                existing_activity = session.exec(
                    select(ScalerActivity).where(
                        ScalerActivity.activity_id == activity_data["id"],
                        ScalerActivity.crm_auth_id == crm_auth.id
                    )
                ).first()
                
                if not existing_activity:
                    # Create new activity
                    new_activity = ScalerActivity(
                        activity_id=activity_data["id"],
                        activity_type=activity_data.get("type", "unknown"),
                        activity_subject=activity_data.get("subject"),
                        activity_description=activity_data.get("description"),
                        activity_date=activity_data.get("date", datetime.utcnow().isoformat()),
                        duration_minutes=activity_data.get("duration"),
                        outcome=activity_data.get("outcome"),
                        next_action=activity_data.get("next_action"),
                        sentiment=activity_data.get("sentiment"),
                        engagement_score=activity_data.get("engagement_score"),
                        raw_data=activity_data,
                        crm_auth_id=crm_auth.id,
                        lead_id=lead_map.get(activity_data.get("lead_id"))
                    )
                    session.add(new_activity)
                    activities_synced += 1
            
            # Check if there are more pages
            if len(result["activities"]) < 100:
                break
            page += 1
        
        session.commit()
        return activities_synced
    
    async def _sync_conversations(
        self,
        session: Session,
        crm_auth: ScalerCRMAuth,
        access_token: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """Sync conversations from CRM"""
        conversations_synced = 0
        page = 1
        
        # Get lead mapping
        lead_map = {}
        leads = session.exec(
            select(ScalerLead).where(ScalerLead.crm_auth_id == crm_auth.id)
        ).all()
        for lead in leads:
            lead_map[lead.lead_id] = lead.id
        
        while True:
            result = await self.get_conversations(
                access_token,
                start_date=start_date,
                end_date=end_date,
                page=page
            )
            if "error" in result or not result.get("conversations"):
                break
            
            for conv_data in result["conversations"]:
                # Check if conversation exists
                existing_conv = session.exec(
                    select(ScalerConversation).where(
                        ScalerConversation.conversation_id == conv_data["id"],
                        ScalerConversation.crm_auth_id == crm_auth.id
                    )
                ).first()
                
                if not existing_conv:
                    # Create new conversation
                    new_conv = ScalerConversation(
                        conversation_id=conv_data["id"],
                        conversation_type=conv_data.get("type", "unknown"),
                        conversation_date=conv_data.get("date", datetime.utcnow().isoformat()),
                        duration_seconds=conv_data.get("duration"),
                        transcript_available=bool(conv_data.get("transcript")),
                        recording_url=conv_data.get("recording_url"),
                        transcript_text=conv_data.get("transcript"),
                        transcript_summary=conv_data.get("summary"),
                        raw_data=conv_data,
                        crm_auth_id=crm_auth.id,
                        lead_id=lead_map.get(conv_data.get("lead_id"))
                    )
                    session.add(new_conv)
                    conversations_synced += 1
                else:
                    # Update transcript if newly available
                    if conv_data.get("transcript") and not existing_conv.transcript_text:
                        existing_conv.transcript_text = conv_data["transcript"]
                        existing_conv.transcript_summary = conv_data.get("summary")
                        existing_conv.transcript_available = True
                        existing_conv.updated_at = datetime.utcnow().isoformat()
                        session.add(existing_conv)
            
            # Check if there are more pages
            if len(result["conversations"]) < 100:
                break
            page += 1
        
        session.commit()
        return conversations_synced
    
    async def calculate_performance_metrics(
        self,
        session: Session,
        crm_auth: ScalerCRMAuth,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Calculate sales performance metrics for a period"""
        try:
            # Get leads in period
            leads = session.exec(
                select(ScalerLead).where(
                    ScalerLead.crm_auth_id == crm_auth.id,
                    ScalerLead.created_date >= start_date.isoformat(),
                    ScalerLead.created_date <= end_date.isoformat()
                )
            ).all()
            
            # Get activities in period
            activities = session.exec(
                select(ScalerActivity).where(
                    ScalerActivity.crm_auth_id == crm_auth.id,
                    ScalerActivity.activity_date >= start_date.isoformat(),
                    ScalerActivity.activity_date <= end_date.isoformat()
                )
            ).all()
            
            # Get conversations in period
            conversations = session.exec(
                select(ScalerConversation).where(
                    ScalerConversation.crm_auth_id == crm_auth.id,
                    ScalerConversation.conversation_date >= start_date.isoformat(),
                    ScalerConversation.conversation_date <= end_date.isoformat()
                )
            ).all()
            
            # Calculate metrics
            total_leads = len(leads)
            qualified_leads = len([l for l in leads if l.lead_status in ["qualified", "converted", "closed"]])
            conversion_rate = (qualified_leads / total_leads * 100) if total_leads > 0 else 0
            
            # Activity breakdown
            activity_types = {}
            for activity in activities:
                activity_types[activity.activity_type] = activity_types.get(activity.activity_type, 0) + 1
            
            # Lead stage distribution
            stage_distribution = {}
            for lead in leads:
                if lead.lead_stage:
                    stage_distribution[lead.lead_stage] = stage_distribution.get(lead.lead_stage, 0) + 1
            
            # Calculate average response time (simplified)
            total_response_time = 0
            response_count = 0
            for activity in activities:
                if activity.activity_type in ["call", "email", "whatsapp"] and activity.lead_id:
                    # This is a simplified calculation
                    response_count += 1
                    total_response_time += 24  # Assume 24 hours average for now
            
            avg_response_time = (total_response_time / response_count) if response_count > 0 else None
            
            return {
                "total_leads": total_leads,
                "total_activities": len(activities),
                "total_conversations": len(conversations),
                "conversion_rate": round(conversion_rate, 2),
                "average_response_time_hours": avg_response_time,
                "activity_breakdown": activity_types,
                "lead_stage_distribution": stage_distribution,
                "conversations_with_transcripts": len([c for c in conversations if c.transcript_available])
            }
            
        except Exception as e:
            logger.error(f"Error calculating metrics: {str(e)}")
            return {}
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()


# Create singleton instance
scaler_crm_service = ScalerCRMService()