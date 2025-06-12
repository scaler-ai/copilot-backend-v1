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
from typing import Any, Dict, List, Optional
import httpx
from sqlmodel import Session, select
from app.core.config import settings
from app.core.encryption import encryption_service
from app.models import (
    User,
    ScalerCRMAuth,
    ScalerLead,
    ScalerActivity,
    ScalerConversation
)

logger = logging.getLogger(__name__)


class ScalerCRMService:
    """Service for interacting with Scaler Sales CRM API"""
    
    def __init__(self):
        self.base_url = settings.SCALER_CRM_API_URL
        self.client = httpx.AsyncClient(timeout=settings.CALL_API_TIMEOUT)
    
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
                f"{self.base_url}/core/users/login",
                json={
                    "user": {
                        "email": email,
                        "password": password
                    }
                },
                headers={
                    "Content-Type": "application/json"
                }
            )
            response.raise_for_status()
            
            data = response.json()
            # According to API documentation, the response has "token" field, not "access_token"
            user_data = data.get("user", {})
            return {
                "success": True,
                "access_token": data.get("token"),  # Changed from "access_token" to "token"
                "refresh_token": data.get("refresh_token"), 
                "expires_in": data.get("expires_in", 3600),
                "user_id": str(user_data.get("id")) if user_data.get("id") else None,
                "user_name": f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip() or email
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"CRM authentication failed: {e.response.status_code}")
            if e.response.status_code == 401:
                return {"success": False, "error": "Invalid credentials"}
            elif e.response.status_code == 404:
                return {"success": False, "error": "CRM API endpoint not found. Please check the API configuration."}
            return {"success": False, "error": f"Authentication failed: {str(e)}"}
        except httpx.ConnectError as e:
            logger.error(f"CRM connection error: {str(e)}")
            return {"success": False, "error": "Unable to connect to Scaler CRM. Please check your network connection and try again."}
        except Exception as e:
            logger.error(f"CRM authentication error: {str(e)}")
            # Check if it's a DNS resolution error
            if "Name or service not known" in str(e) or "nodename nor servname provided" in str(e):
                return {"success": False, "error": "Unable to reach Scaler CRM server. Please verify the CRM is accessible."}
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
        """Fetch leads from CRM using GraphQL"""
        try:
            offset = (page - 1) * per_page
            
            # GraphQL query to fetch leads using correct schema
            query = """
            query GetLeads($limit: Int, $offset: Int, $sortField: String, $sortOrder: String) {
                leadResults(
                    limit: $limit,
                    offset: $offset,
                    sortField: $sortField,
                    sortOrder: $sortOrder
                ) {
                    leads {
                        id
                        leadUuid
                        fullName
                        email
                        isStarred
                        engaged
                        createdAt
                        updatedAt
                        owner {
                            userUuid
                            fullName
                            email
                        }
                        createdBy {
                            userUuid
                            fullName
                            email
                        }
                        combinedLeadAttributeValues {
                            schemaName
                            value
                            dataType
                            leadAttributeId
                            source
                            uniqueField
                        }
                    }
                    totalCount
                    limit
                    offset
                }
            }
            """
            
            variables = {
                "limit": per_page,
                "offset": offset,
                "sortField": "CreatedOn",
                "sortOrder": "desc"
            }
            
            response = await self.client.post(
                f"{self.base_url}/core/graphql",
                json={
                    "query": query,
                    "variables": variables
                },
                headers=self._get_auth_headers(access_token)
            )
            response.raise_for_status()
            
            data = response.json()
            
            if "errors" in data:
                logger.error(f"GraphQL errors: {data['errors']}")
                return {"error": str(data["errors"]), "leads": []}
            
            lead_data = data.get("data", {}).get("leadResults", {})
            leads = lead_data.get("leads", [])
            
            # Transform leads data to our expected format
            transformed_leads = []
            for lead in leads:
                lead_attrs = {}
                for attr_value in lead.get("combinedLeadAttributeValues", []):
                    schema_name = attr_value["schemaName"]
                    lead_attrs[schema_name] = attr_value["value"]
                
                # Extract owner information
                owner = lead.get("owner", {})
                owner_name = owner.get("fullName") if owner else None
                
                transformed_lead = {
                    "id": lead["leadUuid"],
                    "uuid": lead["leadUuid"],
                    "name": lead.get("fullName") or f"{lead_attrs.get('firstName', '')} {lead_attrs.get('lastName', '')}".strip(),
                    "email": lead.get("email") or lead_attrs.get("email"),
                    "phone": lead_attrs.get("phone") or lead_attrs.get("phoneNumber"),
                    "company": lead_attrs.get("company") or lead_attrs.get("companyName"),
                    "designation": lead_attrs.get("designation") or lead_attrs.get("jobTitle"),
                    "source": lead_attrs.get("source") or lead_attrs.get("leadSource"),
                    "status": lead_attrs.get("status") or "new",
                    "stage": lead_attrs.get("stage") or lead_attrs.get("leadStage"),
                    "score": lead_attrs.get("score") or lead_attrs.get("leadScore"),
                    "created_at": lead["createdAt"],
                    "updated_at": lead["updatedAt"],
                    "last_activity_at": lead_attrs.get("lastActivityAt"),
                    "assigned_to_name": owner_name,
                    "assigned_to_id": owner.get("userUuid") if owner else None,
                    "is_starred": lead.get("isStarred", False),
                    "engaged": lead.get("engaged", False),
                    "owner": owner,
                    "attributes": lead_attrs
                }
                transformed_leads.append(transformed_lead)
            
            return {
                "leads": transformed_leads,
                "total": lead_data.get("totalCount", len(transformed_leads)),
                "page": page,
                "per_page": per_page,
                "offset": offset
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to fetch leads: {e.response.status_code}")
            try:
                error_detail = e.response.json()
                logger.error(f"GraphQL error response: {error_detail}")
            except:
                logger.error(f"Response text: {e.response.text}")
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
        """Fetch activities from CRM using GraphQL"""
        try:
            # GraphQL query to fetch lead activities using correct schema
            if lead_id:
                query = """
                query GetLeadActivities($leadUuid: String!, $limit: Int) {
                    leadActivities(leadUuid: $leadUuid, limit: $limit) {
                        leadActivities {
                            id
                            leadActivityUuid
                            activityNote
                            activityTime
                            createdAt
                            activity {
                                displayName
                                activityType
                                direction
                            }
                            owner {
                                userUuid
                                fullName
                                email
                            }
                        }
                        pageInfo {
                            hasNextPage
                            endCursor
                        }
                    }
                }
                """
                variables = {"leadUuid": lead_id, "limit": per_page}
            else:
                # For now, return empty if no lead_id specified
                # The API documentation doesn't show a global activities query
                return {
                    "activities": [],
                    "total": 0,
                    "page": page,
                    "per_page": per_page,
                    "message": "Lead ID required for activities query"
                }
            
            response = await self.client.post(
                f"{self.base_url}/core/graphql",
                json={
                    "query": query,
                    "variables": variables
                },
                headers=self._get_auth_headers(access_token)
            )
            response.raise_for_status()
            
            data = response.json()
            
            if "errors" in data:
                logger.error(f"GraphQL errors: {data['errors']}")
                return {"error": str(data["errors"]), "activities": []}
            
            activity_data = data.get("data", {}).get("leadActivities", {})
            activities = activity_data.get("leadActivities", [])
            
            # Transform activities data to our expected format
            transformed_activities = []
            for activity in activities:
                owner = activity.get("owner", {})
                activity_info = activity.get("activity", {})
                
                transformed_activity = {
                    "id": activity["leadActivityUuid"],
                    "activity_type": activity_info.get("activityType", "unknown"),
                    "activity_name": activity_info.get("displayName"),
                    "direction": activity_info.get("direction"),
                    "notes": activity.get("activityNote"),
                    "activity_time": activity.get("activityTime"),
                    "created_at": activity["createdAt"],
                    "created_by": {
                        "uuid": owner.get("userUuid"),
                        "name": owner.get("fullName"),
                        "email": owner.get("email")
                    } if owner else None,
                    "owner": owner
                }
                transformed_activities.append(transformed_activity)
            
            return {
                "activities": transformed_activities,
                "total": len(transformed_activities),  # GraphQL doesn't return total count for activities
                "page": page,
                "per_page": per_page,
                "has_next_page": activity_data.get("pageInfo", {}).get("hasNextPage", False),
                "end_cursor": activity_data.get("pageInfo", {}).get("endCursor")
            }
            
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
    
    async def get_call_text_analysis(
        self,
        access_token: str,
        lead_uuid: str,
        recruiter_uuid: Optional[str] = None,
        page_size: int = 10,
        page: int = 1
    ) -> Dict[str, Any]:
        """
        Fetch call text analysis (summaries) for a lead using CRM JWT auth.
        
        This API provides:
        - Summary of Call
        - Pain Points
        - Steps to Close
        - Tailored Solutions
        - Background of the Lead
        - Active Objection
        - Objection Reason
        """
        try:
            params = {
                "lead_uuid": lead_uuid,
                "page_size": page_size,
                "page": page
            }
            if recruiter_uuid:
                params["recruiter_uuid"] = recruiter_uuid
            
            # Use CRM subdomain with JWT auth
            api_url = f"{self.base_url}/core/sail_quest/api/v2/call_text_analysis"
            
            response = await self.client.get(
                api_url,
                headers=self._get_auth_headers(access_token),  # Use CRM JWT auth
                params=params
            )
            response.raise_for_status()
            
            return response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching call text analysis: {str(e)}")
            return {"error": str(e), "data": None}
        except Exception as e:
            logger.error(f"Error fetching call text analysis: {str(e)}")
            return {"error": str(e), "data": None}
    
    async def get_call_numerical_analysis(
        self,
        access_token: str,
        lead_uuid: str,
        recruiter_uuid: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetch call numerical analysis (aggregates) for a lead using CRM JWT auth.
        
        This provides numerical metrics and aggregates for calls.
        """
        try:
            params = {"lead_uuid": lead_uuid}
            if recruiter_uuid:
                params["recruiter_uuid"] = recruiter_uuid
            
            # Use CRM subdomain with JWT auth
            api_url = f"{self.base_url}/core/sail_quest/api/v2/call_numerical_analysis"
            
            response = await self.client.get(
                api_url,
                headers=self._get_auth_headers(access_token),  # Use CRM JWT auth
                params=params
            )
            response.raise_for_status()
            
            return response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching call numerical analysis: {str(e)}")
            return {"error": str(e), "data": None}
        except Exception as e:
            logger.error(f"Error fetching call numerical analysis: {str(e)}")
            return {"error": str(e), "data": None}
    
    
    
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
            logger.info(f"Decrypted access token: {access_token[:20] if access_token else 'None'}...")
            
            if not access_token:
                logger.error("Access token is None or empty after decryption")
                return {
                    "success": False,
                    "error": "No valid access token found. Please reconnect to CRM."
                }
            
            # Check if token needs refresh
            if crm_auth.token_expires_at:
                try:
                    expires_at = datetime.fromisoformat(crm_auth.token_expires_at.replace('Z', '+00:00') if crm_auth.token_expires_at.endswith('Z') else crm_auth.token_expires_at)
                except ValueError:
                    logger.warning(f"Could not parse token expiry date: {crm_auth.token_expires_at}")
                    expires_at = datetime.utcnow() - timedelta(minutes=10)  # Force refresh
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
            logger.info("Starting leads sync...")
            leads_synced = await self._sync_leads(session, crm_auth, access_token)
            logger.info(f"Leads sync completed: {leads_synced} leads synced")
            
            # Sync activities
            logger.info("Starting activities sync...")
            activities_synced = await self._sync_activities(
                session, crm_auth, access_token, start_date, end_date
            )
            logger.info(f"Activities sync completed: {activities_synced} activities synced")
            
            # Sync conversations
            logger.info("Starting conversations sync...")
            conversations_synced = await self._sync_conversations(
                session, crm_auth, access_token, start_date, end_date
            )
            logger.info(f"Conversations sync completed: {conversations_synced} conversations synced")
            
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
                    existing_lead.lead_name = lead_data.get("name", "")
                    existing_lead.email = lead_data.get("email")
                    existing_lead.phone = lead_data.get("phone")
                    existing_lead.company = lead_data.get("company")
                    existing_lead.designation = lead_data.get("designation")
                    existing_lead.lead_source = lead_data.get("source")
                    existing_lead.lead_status = lead_data.get("status", "new")
                    existing_lead.lead_stage = lead_data.get("stage")
                    existing_lead.lead_score = lead_data.get("score")
                    existing_lead.last_activity_date = lead_data.get("last_activity_at")
                    existing_lead.assigned_to = lead_data.get("assigned_to_name")
                    existing_lead.assigned_to_id = lead_data.get("assigned_to_id")
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
        
        # Get lead mapping and sync activities for each lead
        leads = session.exec(
            select(ScalerLead).where(ScalerLead.crm_auth_id == crm_auth.id)
        ).all()
        
        logger.info(f"Syncing activities for {len(leads)} leads")
        
        for lead in leads:
            try:
                result = await self.get_activities(
                    access_token, 
                    lead_id=lead.lead_id,  # Pass lead_id as required by the API
                    start_date=start_date,
                    end_date=end_date
                )
                
                if "error" in result:
                    logger.error(f"Error syncing activities for lead {lead.lead_id}: {result['error']}")
                    continue
                
                if not result.get("activities"):
                    logger.debug(f"No activities found for lead {lead.lead_id}")
                    continue
                
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
                            activity_type=activity_data.get("activity_type", "unknown"),
                            activity_subject=activity_data.get("activity_name"),
                            activity_description=activity_data.get("notes"),
                            activity_date=activity_data.get("activity_time") or activity_data.get("created_at", datetime.utcnow().isoformat()),
                            duration_minutes=activity_data.get("duration"),
                            outcome=activity_data.get("outcome"),
                            next_action=activity_data.get("next_action"),
                            sentiment=activity_data.get("sentiment"),
                            engagement_score=activity_data.get("engagement_score"),
                            raw_data=activity_data,
                            crm_auth_id=crm_auth.id,
                            lead_id=lead.id  # Use the database lead ID
                        )
                        session.add(new_activity)
                        activities_synced += 1
                
                logger.info(f"Synced {len(result['activities'])} activities for lead {lead.lead_id}")
                
            except Exception as e:
                logger.error(f"Error syncing activities for lead {lead.lead_id}: {str(e)}")
                continue
        
        session.commit()
        logger.info(f"Total activities synced: {activities_synced}")
        return activities_synced
    
    async def _sync_conversations(
        self,
        session: Session,
        crm_auth: ScalerCRMAuth,
        access_token: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """Sync call conversations using Sail Quest call analysis APIs with CRM JWT auth"""
        conversations_synced = 0
        
        # Check if call transcript sync is enabled
        if not settings.ENABLE_CALL_TRANSCRIPT_SYNC:
            logger.info("Call transcript sync is disabled in configuration")
            return 0
        
        # Get leads and sync conversations for each
        leads = session.exec(
            select(ScalerLead).where(ScalerLead.crm_auth_id == crm_auth.id)
        ).all()
        
        logger.info(f"Syncing call conversations for {len(leads)} leads using Sail Quest APIs")
        
        # Get the recruiter UUID if available
        recruiter_uuid = crm_auth.crm_user_id  # Assuming this contains the UUID
        
        for lead in leads:
            try:
                # Fetch call text analysis for this lead
                text_analysis_result = await self.get_call_text_analysis(
                    access_token,
                    lead_uuid=lead.lead_id,
                    recruiter_uuid=recruiter_uuid,
                    page_size=50,  # Get more calls per page
                    page=1
                )
                
                if "error" in text_analysis_result:
                    logger.error(f"Error fetching call text analysis for lead {lead.lead_id}: {text_analysis_result['error']}")
                    continue
                
                # Also fetch numerical analysis for metrics
                numerical_analysis_result = await self.get_call_numerical_analysis(
                    access_token,
                    lead_uuid=lead.lead_id,
                    recruiter_uuid=recruiter_uuid
                )
                
                # Process text analysis data (contains call summaries)
                if text_analysis_result and not text_analysis_result.get("error"):
                    # The response structure will contain call analysis data
                    # Adjust based on actual API response format
                    calls_data = text_analysis_result.get("data", {}).get("calls", [])
                    if isinstance(text_analysis_result.get("data"), list):
                        calls_data = text_analysis_result.get("data", [])
                    
                    logger.info(f"Found {len(calls_data)} call analyses for lead {lead.lead_id}")
                    
                    for call_analysis in calls_data:
                        try:
                            # Create a unique conversation ID
                            call_id = call_analysis.get("call_id") or call_analysis.get("id")
                            conversation_id = f"call_{lead.lead_id}_{call_id}"
                            
                            # Check if conversation exists
                            existing_conv = session.exec(
                                select(ScalerConversation).where(
                                    ScalerConversation.conversation_id == conversation_id,
                                    ScalerConversation.crm_auth_id == crm_auth.id
                                )
                            ).first()
                            
                            # Parse call date
                            call_date_str = call_analysis.get("call_date") or call_analysis.get("created_at")
                            if call_date_str:
                                try:
                                    call_date = datetime.fromisoformat(call_date_str.replace('Z', '+00:00'))
                                except:
                                    call_date = datetime.utcnow()
                            else:
                                call_date = datetime.utcnow()
                            
                            if not existing_conv:
                                # Create new conversation record with Sail Quest data
                                new_conv = ScalerConversation(
                                    conversation_id=conversation_id,
                                    conversation_type="call",
                                    conversation_date=call_date.isoformat(),
                                    duration_seconds=call_analysis.get("duration_seconds", 0),
                                    transcript_available=True,  # Text analysis means transcript exists
                                    recording_url=call_analysis.get("recording_url"),
                                    transcript_text=call_analysis.get("transcript"),  # If full transcript provided
                                    transcript_summary=call_analysis.get("summary_of_call") or call_analysis.get("summary"),
                                    raw_data={
                                        "text_analysis": call_analysis,
                                        "pain_points": call_analysis.get("pain_points"),
                                        "steps_to_close": call_analysis.get("steps_to_close"),
                                        "tailored_solutions": call_analysis.get("tailored_solutions"),
                                        "background_of_lead": call_analysis.get("background_of_the_lead"),
                                        "active_objection": call_analysis.get("active_objection"),
                                        "objection_reason": call_analysis.get("objection_reason")
                                    },
                                    crm_auth_id=crm_auth.id,
                                    lead_id=lead.id
                                )
                                
                                session.add(new_conv)
                                conversations_synced += 1
                                logger.info(f"Created conversation record for call {conversation_id}")
                            else:
                                # Update existing conversation with new analysis data
                                existing_conv.transcript_summary = call_analysis.get("summary_of_call") or call_analysis.get("summary")
                                existing_conv.raw_data = {
                                    "text_analysis": call_analysis,
                                    "pain_points": call_analysis.get("pain_points"),
                                    "steps_to_close": call_analysis.get("steps_to_close"),
                                    "tailored_solutions": call_analysis.get("tailored_solutions"),
                                    "background_of_lead": call_analysis.get("background_of_the_lead"),
                                    "active_objection": call_analysis.get("active_objection"),
                                    "objection_reason": call_analysis.get("objection_reason")
                                }
                                existing_conv.updated_at = datetime.utcnow().isoformat()
                                session.add(existing_conv)
                                logger.info(f"Updated conversation record for call {conversation_id}")
                        
                        except Exception as e:
                            logger.error(f"Error processing call analysis for lead {lead.lead_id}: {str(e)}")
                            continue
                
                # Store numerical analysis data if needed
                if numerical_analysis_result and not numerical_analysis_result.get("error"):
                    logger.info(f"Fetched numerical analysis for lead {lead.lead_id}")
                    # Could store aggregate metrics in lead metadata or separate table
                
            except Exception as e:
                logger.error(f"Error syncing conversations for lead {lead.lead_id}: {str(e)}")
                continue
        
        session.commit()
        logger.info(f"Total call conversations synced: {conversations_synced}")
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
    
    async def sync_team_member_data(
        self,
        session: Session,
        member_user: User,
        member_crm_auth: ScalerCRMAuth,
        manager_crm_auth: ScalerCRMAuth,
        member_email: str,
        months_to_sync: int = 3
    ) -> Dict[str, Any]:
        """
        Sync a team member's CRM data using their manager's auth token.
        Only syncs data that belongs to the specific team member.
        """
        try:
            # Decrypt manager's access token
            access_token = encryption_service.decrypt(manager_crm_auth.encrypted_access_token)
            
            if not access_token:
                logger.error("Manager's access token is None or empty after decryption")
                member_crm_auth.sync_status = "failed"
                session.add(member_crm_auth)
                session.commit()
                return {
                    "success": False,
                    "error": "Manager's access token invalid. Manager needs to reconnect to CRM."
                }
            
            # Update sync status
            member_crm_auth.sync_status = "syncing"
            member_crm_auth.updated_at = datetime.utcnow().isoformat()
            session.add(member_crm_auth)
            session.commit()
            
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=months_to_sync * 30)
            
            # Extract member name variations for filtering
            member_name_parts = member_email.split('@')[0].split('.')
            member_variations = [
                member_email.lower(),
                ' '.join(member_name_parts).lower(),
                '.'.join(member_name_parts).lower()
            ]
            
            logger.info(f"Starting sync for team member: {member_email}")
            logger.info(f"Using name variations: {member_variations}")
            
            # Sync leads assigned to the team member
            leads_synced = await self._sync_team_member_leads(
                session, member_crm_auth, access_token, member_variations
            )
            logger.info(f"Leads sync completed: {leads_synced} leads synced")
            
            # Sync activities for the member's leads
            activities_synced = await self._sync_team_member_activities(
                session, member_crm_auth, access_token, start_date, end_date
            )
            logger.info(f"Activities sync completed: {activities_synced} activities synced")
            
            # Sync conversations for the member's leads
            conversations_synced = await self._sync_team_member_conversations(
                session, member_crm_auth, access_token, start_date, end_date
            )
            logger.info(f"Conversations sync completed: {conversations_synced} conversations synced")
            
            # Update sync status
            member_crm_auth.sync_status = "completed"
            member_crm_auth.last_sync_at = datetime.utcnow().isoformat()
            session.add(member_crm_auth)
            session.commit()
            
            return {
                "success": True,
                "leads_synced": leads_synced,
                "activities_synced": activities_synced,
                "conversations_synced": conversations_synced,
                "sync_date": member_crm_auth.last_sync_at
            }
            
        except Exception as e:
            logger.error(f"Team member sync failed: {str(e)}")
            member_crm_auth.sync_status = "failed"
            session.add(member_crm_auth)
            session.commit()
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _sync_team_member_leads(
        self,
        session: Session,
        member_crm_auth: ScalerCRMAuth,
        access_token: str,
        member_variations: List[str]
    ) -> int:
        """Sync only leads assigned to the specific team member"""
        leads_synced = 0
        page = 1
        
        while True:
            result = await self.get_leads(access_token, page=page, per_page=100)
            if "error" in result or not result.get("leads"):
                break
            
            for lead_data in result["leads"]:
                # Check if lead is assigned to the team member
                assigned_to = (lead_data.get("assigned_to_name") or "").lower()
                owner_email = ""
                owner_name = ""
                
                if "owner" in lead_data and lead_data["owner"]:
                    owner_email = (lead_data["owner"].get("email") or "").lower()
                    owner_name = (lead_data["owner"].get("fullName") or "").lower()
                
                # Check if this lead belongs to the team member
                is_member_lead = any(
                    variation in assigned_to or 
                    variation in owner_email or 
                    variation in owner_name
                    for variation in member_variations
                )
                
                if is_member_lead:
                    # Process this lead
                    existing_lead = session.exec(
                        select(ScalerLead).where(
                            ScalerLead.lead_id == lead_data["id"],
                            ScalerLead.crm_auth_id == member_crm_auth.id
                        )
                    ).first()
                    
                    if existing_lead:
                        # Update existing lead
                        existing_lead.lead_name = lead_data.get("name", "")
                        existing_lead.email = lead_data.get("email")
                        existing_lead.phone = lead_data.get("phone")
                        existing_lead.company = lead_data.get("company")
                        existing_lead.lead_status = lead_data.get("status", "new")
                        existing_lead.lead_stage = lead_data.get("stage")
                        existing_lead.assigned_to = lead_data.get("assigned_to_name")
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
                            lead_source=lead_data.get("source"),
                            lead_status=lead_data.get("status", "new"),
                            lead_stage=lead_data.get("stage"),
                            created_date=lead_data.get("created_at"),
                            assigned_to=lead_data.get("assigned_to_name"),
                            raw_data=lead_data,
                            crm_auth_id=member_crm_auth.id
                        )
                        session.add(new_lead)
                    
                    leads_synced += 1
            
            # Check if there are more pages
            if len(result["leads"]) < 100:
                break
            page += 1
        
        session.commit()
        return leads_synced
    
    async def _sync_team_member_activities(
        self,
        session: Session,
        member_crm_auth: ScalerCRMAuth,
        access_token: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """Sync activities for team member's leads only"""
        activities_synced = 0
        
        # Get member's leads
        member_leads = session.exec(
            select(ScalerLead).where(ScalerLead.crm_auth_id == member_crm_auth.id)
        ).all()
        
        logger.info(f"Syncing activities for {len(member_leads)} member leads")
        
        for lead in member_leads:
            try:
                result = await self.get_activities(
                    access_token,
                    lead_id=lead.lead_id,
                    start_date=start_date,
                    end_date=end_date,
                    per_page=100
                )
                
                if "error" in result:
                    logger.error(f"Error syncing activities for lead {lead.lead_id}: {result['error']}")
                    continue
                
                for activity_data in result.get("activities", []):
                    existing_activity = session.exec(
                        select(ScalerActivity).where(
                            ScalerActivity.activity_id == activity_data["id"],
                            ScalerActivity.crm_auth_id == member_crm_auth.id
                        )
                    ).first()
                    
                    if not existing_activity:
                        new_activity = ScalerActivity(
                            activity_id=activity_data["id"],
                            activity_type=activity_data.get("activity_type", "unknown"),
                            activity_subject=activity_data.get("activity_name"),
                            activity_description=activity_data.get("notes"),
                            activity_date=activity_data.get("activity_time") or activity_data.get("created_at"),
                            raw_data=activity_data,
                            crm_auth_id=member_crm_auth.id,
                            lead_id=lead.id
                        )
                        session.add(new_activity)
                        activities_synced += 1
                
            except Exception as e:
                logger.error(f"Error syncing activities for lead {lead.lead_id}: {str(e)}")
                continue
        
        session.commit()
        return activities_synced
    
    async def _sync_team_member_conversations(
        self,
        session: Session,
        member_crm_auth: ScalerCRMAuth,
        access_token: str,
        start_date: datetime,
        end_date: datetime
    ) -> int:
        """Sync conversations for team member's leads only"""
        conversations_synced = 0
        
        # Get member's leads (limit to prevent timeout)
        member_leads = session.exec(
            select(ScalerLead).where(ScalerLead.crm_auth_id == member_crm_auth.id).limit(20)
        ).all()
        
        logger.info(f"Syncing conversations for {len(member_leads)} member leads")
        
        for lead in member_leads:
            try:
                # Get call text analysis
                text_result = await self.get_call_text_analysis(
                    access_token=access_token,
                    lead_uuid=lead.lead_id,
                    page_size=10,
                    page=1
                )
                
                if not text_result.get("error") and text_result.get("data"):
                    calls_data = text_result.get("data", {}).get("data", [])
                    if isinstance(text_result.get("data"), list):
                        calls_data = text_result.get("data", [])
                    
                    for call_data in calls_data:
                        conversation_id = call_data.get("call_id") or call_data.get("id")
                        if conversation_id:
                            existing_conv = session.exec(
                                select(ScalerConversation).where(
                                    ScalerConversation.conversation_id == str(conversation_id),
                                    ScalerConversation.crm_auth_id == member_crm_auth.id
                                )
                            ).first()
                            
                            if not existing_conv:
                                new_conv = ScalerConversation(
                                    conversation_id=str(conversation_id),
                                    conversation_type="call",
                                    conversation_date=call_data.get("date") or datetime.utcnow().isoformat(),
                                    duration_seconds=call_data.get("duration", 0),
                                    transcript_available=True,
                                    transcript_summary=call_data.get("summary_of_call") or call_data.get("summary"),
                                    sentiment_score=call_data.get("call_score"),
                                    raw_data=call_data,
                                    crm_auth_id=member_crm_auth.id,
                                    lead_id=lead.id
                                )
                                session.add(new_conv)
                                conversations_synced += 1
                
            except Exception as e:
                logger.error(f"Error syncing conversations for lead {lead.lead_id}: {str(e)}")
                continue
        
        session.commit()
        return conversations_synced

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()


# Create singleton instance
scaler_crm_service = ScalerCRMService()