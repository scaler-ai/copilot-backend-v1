"""
DarwinBox Integration Service
Handles API communication and data processing for DarwinBox HR system
"""
import base64
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

import httpx
from sqlmodel import Session, select, func

from app.core.config import settings
from app.models import (
    DarwinBoxEmployee,
    DarwinBoxEmployeePublic,
    EmployeeGitHubMapping,
    GitHubOAuth,
    GitHubContributor,
    User,
)

logger = logging.getLogger(__name__)


class DarwinBoxService:
    """Service for interacting with DarwinBox API"""
    
    def __init__(self):
        # Get credentials from environment variables
        self.base_url = getattr(settings, 'DARWINBOX_BASE_URL', 'https://interviewbit.darwinbox.in')
        self.api_key = getattr(settings, 'DARWINBOX_API_KEY', '')
        self.dataset_key = getattr(settings, 'DARWINBOX_DATASET_KEY', '')
        self.basic_auth = getattr(settings, 'DARWINBOX_BASIC_AUTH', '')
        
        # If basic auth not set directly, build from username:password
        if not self.basic_auth:
            username = getattr(settings, 'DARWINBOX_USERNAME', '')
            password = getattr(settings, 'DARWINBOX_PASSWORD', '')
            if username and password:
                self.basic_auth = base64.b64encode(f"{username}:{password}".encode()).decode()
        
        # Ensure credentials are configured
        if not self.basic_auth:
            raise ValueError("DarwinBox Basic Auth not configured. Set DARWINBOX_BASIC_AUTH in environment.")
    
    async def fetch_employees(self, session: Session, include_inactive: bool = False) -> dict[str, Any]:
        """
        Fetch employee data from DarwinBox API
        
        Args:
            session: Database session
            include_inactive: Whether to include inactive employees
            
        Returns:
            Dictionary with employee data and sync statistics
        """
        start_time = time.time()
        
        try:
            async with httpx.AsyncClient() as client:
                headers = {
                    "Authorization": f"Basic {self.basic_auth}",
                    "Content-Type": "application/json"
                }
                
                # Prepare request body from environment configuration
                request_data = {
                    "api_key": self.api_key,
                    "datasetKey": self.dataset_key
                }
                
                if not self.api_key or not self.dataset_key:
                    raise ValueError("DarwinBox API credentials not configured")
                
                logger.info(f"DarwinBox request - URL: {self.base_url}/masterapi/employee")
                logger.info(f"DarwinBox request - Auth header: {headers['Authorization'][:20]}...")
                logger.info(f"DarwinBox request - Body keys: {list(request_data.keys())}")
                
                if include_inactive:
                    request_data["status"] = "all"
                else:
                    request_data["status"] = "active"
                
                # Make API request
                response = await client.post(
                    f"{self.base_url}/masterapi/employee",
                    headers=headers,
                    json=request_data,
                    timeout=30.0
                )
                
                response.raise_for_status()
                data = response.json()
                
                if not isinstance(data, dict) or "employee_data" not in data:
                    logger.error(f"Unexpected API response format: {data}")
                    raise ValueError("Invalid API response format")
                
                employees = data.get("employee_data", [])
                
                # Process and return employee data
                return {
                    "success": True,
                    "employees": employees,
                    "total_count": len(employees),
                    "sync_duration": time.time() - start_time
                }
                
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching DarwinBox employees: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching DarwinBox employees: {e}")
            raise
    
    def map_employee_data(self, raw_employee: dict[str, Any]) -> dict[str, Any]:
        """
        Map raw DarwinBox employee data to our model fields
        
        Args:
            raw_employee: Raw employee data from API
            
        Returns:
            Mapped employee data
        """
        # Map fields based on typical DarwinBox API response
        # Adjust these mappings based on actual API response structure
        return {
            "darwinbox_id": str(raw_employee.get("employee_id", "")),
            "employee_code": raw_employee.get("employee_code"),  # May not be present in API
            "full_name": raw_employee.get("full_name", ""),
            "email": raw_employee.get("company_email_id", "") or raw_employee.get("personal_email_id", ""),
            "designation": raw_employee.get("designation", ""),
            "department": raw_employee.get("department", ""),
            "location": raw_employee.get("location", ""),  # May not be present in API
            "reporting_manager_id": str(raw_employee.get("direct_manager_employee_id", "")),
            "reporting_manager_name": raw_employee.get("direct_manager_name", ""),
            "date_of_joining": raw_employee.get("date_of_joining", ""),
            "employment_status": "active",  # API doesn't seem to provide status, default to active
            "phone_number": raw_employee.get("personal_mobile_no", "").lstrip("'"),  # Remove leading quote
            "grade": raw_employee.get("grade", ""),
            "business_unit": raw_employee.get("business_unit", ""),
            "cost_center": raw_employee.get("cost_center", ""),  # May not be present in API
            "is_manager": False,  # Will need to determine based on whether they have direct reports
            "employee_type": raw_employee.get("employee_type", ""),
            "raw_data": raw_employee  # Store complete data for reference
        }
    
    def _map_employment_status(self, status: str) -> str:
        """Map DarwinBox status to our status values"""
        status = status.lower().strip()
        if status in ["active", "1", "true"]:
            return "active"
        elif status in ["inactive", "0", "false"]:
            return "inactive"
        elif status in ["terminated", "exit", "resigned"]:
            return "terminated"
        else:
            return "active"  # Default to active
    
    async def sync_employees(
        self,
        session: Session,
        current_user: User,
        include_inactive: bool = False,
        specific_employee_ids: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """
        Sync employees from DarwinBox to local database
        
        Args:
            session: Database session
            current_user: User performing the sync
            include_inactive: Whether to include inactive employees
            specific_employee_ids: Specific employee IDs to sync (if None, sync all)
            
        Returns:
            Sync statistics
        """
        start_time = time.time()
        
        try:
            # Fetch employees from API
            result = await self.fetch_employees(session, include_inactive)
            employees = result["employees"]
            
            # Filter specific employees if requested
            if specific_employee_ids:
                employees = [emp for emp in employees if str(emp.get("emp_id", "")) in specific_employee_ids]
            
            # Track statistics
            created = 0
            updated = 0
            errors = []
            
            for raw_employee in employees:
                try:
                    # Map employee data
                    employee_data = self.map_employee_data(raw_employee)
                    darwinbox_id = employee_data["darwinbox_id"]
                    
                    if not darwinbox_id:
                        errors.append(f"Missing employee ID for: {employee_data.get('full_name', 'Unknown')}")
                        continue
                    
                    # Check if employee exists
                    existing = session.exec(
                        select(DarwinBoxEmployee).where(DarwinBoxEmployee.darwinbox_id == darwinbox_id)
                    ).first()
                    
                    now = datetime.utcnow().isoformat()
                    
                    if existing:
                        # Update existing employee
                        for key, value in employee_data.items():
                            if key != "raw_data" or value is not None:  # Don't overwrite with None except raw_data
                                setattr(existing, key, value)
                        existing.updated_at = now
                        existing.last_sync_at = now
                        session.add(existing)
                        updated += 1
                    else:
                        # Create new employee
                        new_employee = DarwinBoxEmployee(
                            **employee_data,
                            created_at=now,
                            updated_at=now,
                            last_sync_at=now,
                            synced_by_id=current_user.id
                        )
                        session.add(new_employee)
                        created += 1
                    
                except Exception as e:
                    error_msg = f"Error processing employee {raw_employee.get('emp_id', 'Unknown')}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
            
            session.commit()
            
            # Format errors properly
            formatted_errors = [{"message": err, "type": "sync_error"} for err in errors]
            
            return {
                "sync_id": f"sync_{int(time.time())}",
                "status": "completed",
                "message": f"Successfully synced {created + updated} employees",
                "sync_type": "employees",
                "started_at": datetime.utcnow().isoformat(),
                "estimated_completion_time": None,
                "total_records_to_process": len(employees),
                "records_processed": len(employees),
                "records_created": created,
                "records_updated": updated,
                "records_failed": len(errors),
                "errors": formatted_errors,
                "warnings": [],
                "dry_run": False,
                "sync_details": {
                    "employees_synced": len(employees),
                    "sync_duration_seconds": time.time() - start_time
                }
            }
            
        except Exception as e:
            logger.error(f"Error syncing DarwinBox employees: {e}")
            raise
    
    async def auto_map_github_accounts(
        self,
        session: Session,
        current_user: User
    ) -> dict[str, Any]:
        """
        Automatically map DarwinBox employees to GitHub accounts based on email matching
        
        Args:
            session: Database session
            current_user: User performing the mapping
            
        Returns:
            Mapping statistics
        """
        try:
            # Get all employees without GitHub mapping
            employees_without_mapping = session.exec(
                select(DarwinBoxEmployee)
                .where(DarwinBoxEmployee.github_mapping == None)
            ).all()
            
            mapped_count = 0
            potential_matches = []
            
            # Get all GitHub contributors with email
            github_contributors = session.exec(
                select(GitHubContributor)
                .where(GitHubContributor.email != None)
            ).all()
            
            # Create email to contributor mapping
            email_to_github = {contrib.email.lower(): contrib for contrib in github_contributors if contrib.email}
            
            for employee in employees_without_mapping:
                if not employee.email:
                    continue
                
                employee_email = employee.email.lower()
                
                # Check for exact email match
                if employee_email in email_to_github:
                    contributor = email_to_github[employee_email]
                    
                    # Create mapping
                    mapping = EmployeeGitHubMapping(
                        darwinbox_employee_id=employee.id,
                        github_username=contributor.login,
                        github_id=contributor.github_id,
                        mapping_verified=True,
                        verification_method="email_match",
                        verification_notes=f"Auto-mapped based on email: {employee_email}",
                        created_at=datetime.utcnow().isoformat(),
                        updated_at=datetime.utcnow().isoformat(),
                        mapped_by_id=current_user.id
                    )
                    session.add(mapping)
                    mapped_count += 1
                else:
                    # Check for potential matches (similar email patterns)
                    email_prefix = employee_email.split('@')[0]
                    for github_email, contributor in email_to_github.items():
                        if email_prefix in github_email or github_email.startswith(email_prefix):
                            potential_matches.append({
                                "employee_name": employee.full_name,
                                "employee_email": employee.email,
                                "github_username": contributor.login,
                                "github_email": contributor.email,
                                "confidence": "medium"
                            })
            
            session.commit()
            
            return {
                "success": True,
                "mapped_count": mapped_count,
                "potential_matches": potential_matches[:20],  # Limit to 20 suggestions
                "total_unmapped": len(employees_without_mapping) - mapped_count
            }
            
        except Exception as e:
            logger.error(f"Error auto-mapping GitHub accounts: {e}")
            raise
    
    def get_team_hierarchy(
        self,
        session: Session,
        manager_id: str,
        include_skills: bool = True
    ) -> dict[str, Any]:
        """
        Get team hierarchy for a manager
        
        Args:
            session: Database session
            manager_id: DarwinBox ID of the manager
            include_skills: Whether to include skill information
            
        Returns:
            Team hierarchy data
        """
        try:
            # Get manager details
            manager = session.exec(
                select(DarwinBoxEmployee).where(DarwinBoxEmployee.darwinbox_id == manager_id)
            ).first()
            
            if not manager:
                raise ValueError(f"Manager with ID {manager_id} not found")
            
            # Get direct reports
            direct_reports = session.exec(
                select(DarwinBoxEmployee).where(DarwinBoxEmployee.reporting_manager_id == manager_id)
            ).all()
            
            # Build team structure
            team_data = {
                "manager": self._employee_to_public(manager, session),
                "direct_reports": [],
                "total_team_size": len(direct_reports),
                "github_integration_stats": {
                    "mapped": 0,
                    "unmapped": 0
                }
            }
            
            for report in direct_reports:
                report_data = self._employee_to_public(report, session)
                
                # Check GitHub mapping
                if report.github_mapping:
                    team_data["github_integration_stats"]["mapped"] += 1
                else:
                    team_data["github_integration_stats"]["unmapped"] += 1
                
                # Get sub-team size
                sub_team_count = session.exec(
                    select(func.count(DarwinBoxEmployee.id))
                    .where(DarwinBoxEmployee.reporting_manager_id == report.darwinbox_id)
                ).one()
                
                report_data["team_size"] = sub_team_count
                team_data["direct_reports"].append(report_data)
            
            # Include skill summary if requested
            if include_skills:
                team_data["skill_summary"] = self._get_team_skill_summary(
                    session, manager_id, direct_reports
                )
            
            return team_data
            
        except Exception as e:
            logger.error(f"Error getting team hierarchy: {e}")
            raise
    
    def _employee_to_public(self, employee: DarwinBoxEmployee, session: Session) -> dict[str, Any]:
        """Convert DarwinBoxEmployee to public format with GitHub mapping info"""
        # For better performance, use a direct query to check mapping
        # This avoids lazy loading issues
        github_mapping = session.exec(
            select(EmployeeGitHubMapping).where(
                EmployeeGitHubMapping.darwinbox_employee_id == employee.id
            )
        ).first()
        
        public_data = {
            "id": str(employee.id),
            "darwinbox_id": employee.darwinbox_id,
            "employee_code": employee.employee_code,
            "full_name": employee.full_name,
            "email": employee.email,
            "designation": employee.designation,
            "department": employee.department,
            "location": employee.location,
            "reporting_manager_id": employee.reporting_manager_id,
            "reporting_manager_name": employee.reporting_manager_name,
            "date_of_joining": employee.date_of_joining,
            "employment_status": employee.employment_status,
            "phone_number": employee.phone_number,
            "grade": employee.grade,
            "business_unit": employee.business_unit,
            "cost_center": employee.cost_center,
            "is_manager": employee.is_manager,
            "employee_type": employee.employee_type,
            "created_at": employee.created_at,
            "updated_at": employee.updated_at,
            "last_sync_at": employee.last_sync_at,
            "has_github_mapping": bool(github_mapping),
            "github_username": github_mapping.github_username if github_mapping else None
        }
        
        return public_data
    
    def _get_team_skill_summary(
        self,
        session: Session,
        manager_id: str,
        team_members: list[DarwinBoxEmployee]
    ) -> dict[str, Any]:
        """Get aggregated skill summary for a team"""
        # This is a placeholder - would integrate with skill service
        # to get actual skills from GitHub analysis
        skill_summary = {
            "top_skills": [],
            "skill_gaps": [],
            "average_skill_level": 0,
            "skills_coverage": 0
        }
        
        # Count team members with GitHub mappings and skills
        members_with_skills = 0
        for member in team_members:
            if member.github_mapping:
                # Check if they have GitHub analysis
                # This would query ContributorAnalysis table
                members_with_skills += 1
        
        skill_summary["skills_coverage"] = (
            (members_with_skills / len(team_members) * 100) if team_members else 0
        )
        
        return skill_summary


# Global service instance
darwinbox_service = DarwinBoxService()