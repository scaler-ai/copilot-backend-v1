"""
DarwinBox Integration API Routes
"""
import logging
import time
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlmodel import select, func, or_
import httpx

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    DarwinBoxEmployee,
    DarwinBoxEmployeePublic,
    DarwinBoxEmployeesPublic,
    DarwinBoxSyncRequest,
    DarwinBoxSyncResponse,
    EmployeeGitHubMapping,
    EmployeeGitHubMappingCreate,
    EmployeeGitHubMappingPublic,
    EmployeeGitHubMappingUpdate,
    EmployeeSearchParams,
    TeamWithSkillsResponse,
    Message,
    GitHubContributor,
    GitHubOAuth,
    User,
    UserSkill,
    ContributorAnalysis,
    BatchMappingReview,
    BatchMappingReviewResponse,
    MappingReviewItem,
)
from app.services.darwinbox_service import darwinbox_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/sync-employees", response_model=DarwinBoxSyncResponse)
async def sync_darwinbox_employees(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    sync_request: DarwinBoxSyncRequest
) -> Any:
    """
    Sync employee data from DarwinBox.
    Requires superuser privileges.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Only superusers can sync DarwinBox data"
        )
    
    try:
        # Perform sync based on request type
        result = await darwinbox_service.sync_employees(
            session=session,
            current_user=current_user,
            include_inactive=sync_request.include_inactive
        )
        
        # Ensure all required fields are present
        sync_response = DarwinBoxSyncResponse(
            sync_id=result.get("sync_id", f"sync_{int(time.time())}"),
            status=result.get("status", "completed"),
            message=result.get("message", "Sync completed"),
            sync_type=result.get("sync_type", "employees"),
            started_at=result.get("started_at", datetime.utcnow().isoformat()),
            estimated_completion_time=result.get("estimated_completion_time"),
            total_records_to_process=result.get("total_records_to_process", 0),
            records_processed=result.get("records_processed", 0),
            records_created=result.get("records_created", 0),
            records_updated=result.get("records_updated", 0),
            records_failed=result.get("records_failed", 0),
            errors=result.get("errors", []),
            warnings=result.get("warnings", []),
            dry_run=result.get("dry_run", False),
            sync_details=result.get("sync_details", {})
        )
        
        return sync_response
        
    except Exception as e:
        logger.error(f"Error syncing DarwinBox employees: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync employees: {str(e)}"
        )


@router.get("/employees", response_model=DarwinBoxEmployeesPublic)
def get_darwinbox_employees(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    department: Optional[str] = None,
    location: Optional[str] = None,
    has_github_mapping: Optional[bool] = None,
    is_manager: Optional[bool] = None,
    employment_status: str = "active"
) -> Any:
    """
    Get list of DarwinBox employees with optional filters.
    """
    # Build query with relationship
    from sqlmodel import col
    query = select(DarwinBoxEmployee)
    
    # Apply filters
    if employment_status and employment_status != "all":
        query = query.where(DarwinBoxEmployee.employment_status == employment_status)
    
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                DarwinBoxEmployee.full_name.ilike(search_term),
                DarwinBoxEmployee.email.ilike(search_term),
                DarwinBoxEmployee.darwinbox_id.ilike(search_term),
                DarwinBoxEmployee.employee_code.ilike(search_term)
            )
        )
    
    if department:
        query = query.where(DarwinBoxEmployee.department == department)
    
    if location:
        query = query.where(DarwinBoxEmployee.location == location)
    
    if is_manager is not None:
        query = query.where(DarwinBoxEmployee.is_manager == is_manager)
    
    if has_github_mapping is not None:
        # Check existence of related EmployeeGitHubMapping
        subquery = select(EmployeeGitHubMapping.darwinbox_employee_id).where(
            EmployeeGitHubMapping.darwinbox_employee_id == DarwinBoxEmployee.id
        )
        if has_github_mapping:
            query = query.where(DarwinBoxEmployee.id.in_(subquery))
        else:
            query = query.where(DarwinBoxEmployee.id.not_in(subquery))
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_count = session.exec(count_query).one()
    
    # Apply pagination
    query = query.offset(skip).limit(limit).order_by(DarwinBoxEmployee.full_name)
    employees = session.exec(query).all()
    
    # Convert to public format
    employees_public = []
    for employee in employees:
        public_employee = darwinbox_service._employee_to_public(employee, session)
        employees_public.append(DarwinBoxEmployeePublic(**public_employee))
    
    return DarwinBoxEmployeesPublic(
        data=employees_public,
        count=total_count
    )


@router.get("/employees/{employee_id}", response_model=DarwinBoxEmployeePublic)
def get_darwinbox_employee(
    employee_id: UUID,
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Get a specific DarwinBox employee by ID.
    """
    employee = session.get(DarwinBoxEmployee, employee_id)
    
    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )
    
    public_employee = darwinbox_service._employee_to_public(employee, session)
    return DarwinBoxEmployeePublic(**public_employee)


@router.post("/map-employee", response_model=EmployeeGitHubMappingPublic)
def create_employee_github_mapping(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    mapping_data: EmployeeGitHubMappingCreate
) -> Any:
    """
    Manually map a DarwinBox employee to a GitHub account.
    """
    # Verify employee exists
    employee = session.get(DarwinBoxEmployee, mapping_data.darwinbox_employee_id)
    if not employee:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )
    
    # Check if mapping already exists
    existing_mapping = session.exec(
        select(EmployeeGitHubMapping).where(
            EmployeeGitHubMapping.darwinbox_employee_id == mapping_data.darwinbox_employee_id
        )
    ).first()
    
    if existing_mapping:
        raise HTTPException(
            status_code=400,
            detail="Employee already has a GitHub mapping"
        )
    
    # Try to find GitHub contributor
    github_contributor = session.exec(
        select(GitHubContributor).where(
            GitHubContributor.login == mapping_data.github_username
        )
    ).first()
    
    # Create mapping
    new_mapping = EmployeeGitHubMapping(
        darwinbox_employee_id=mapping_data.darwinbox_employee_id,
        github_username=mapping_data.github_username,
        github_id=github_contributor.github_id if github_contributor else None,
        mapping_verified=mapping_data.verification_method == "api_verified",
        verification_method=mapping_data.verification_method,
        verification_notes=mapping_data.verification_notes,
        mapped_by_id=current_user.id
    )
    
    session.add(new_mapping)
    session.commit()
    session.refresh(new_mapping)
    
    return EmployeeGitHubMappingPublic(
        id=new_mapping.id,
        darwinbox_employee_id=new_mapping.darwinbox_employee_id,
        github_username=new_mapping.github_username,
        github_id=new_mapping.github_id,
        mapping_verified=new_mapping.mapping_verified,
        verification_method=new_mapping.verification_method,
        verification_notes=new_mapping.verification_notes,
        created_at=new_mapping.created_at,
        updated_at=new_mapping.updated_at,
        employee_name=employee.full_name,
        employee_email=employee.email
    )


@router.put("/map-employee/{mapping_id}", response_model=EmployeeGitHubMappingPublic)
def update_employee_github_mapping(
    mapping_id: UUID,
    session: SessionDep,
    current_user: CurrentUser,
    update_data: EmployeeGitHubMappingUpdate
) -> Any:
    """
    Update an existing employee GitHub mapping.
    """
    mapping = session.get(EmployeeGitHubMapping, mapping_id)
    
    if not mapping:
        raise HTTPException(
            status_code=404,
            detail="Mapping not found"
        )
    
    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(mapping, field, value)
    
    mapping.updated_at = datetime.utcnow().isoformat()
    
    # Update GitHub ID if username changed
    if update_data.github_username:
        github_contributor = session.exec(
            select(GitHubContributor).where(
                GitHubContributor.login == update_data.github_username
            )
        ).first()
        mapping.github_id = github_contributor.github_id if github_contributor else None
    
    session.add(mapping)
    session.commit()
    session.refresh(mapping)
    
    # Get employee details
    employee = mapping.darwinbox_employee
    
    return EmployeeGitHubMappingPublic(
        id=mapping.id,
        darwinbox_employee_id=mapping.darwinbox_employee_id,
        github_username=mapping.github_username,
        github_id=mapping.github_id,
        mapping_verified=mapping.mapping_verified,
        verification_method=mapping.verification_method,
        verification_notes=mapping.verification_notes,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
        employee_name=employee.full_name,
        employee_email=employee.email
    )


@router.delete("/map-employee/{mapping_id}")
def delete_employee_github_mapping(
    mapping_id: UUID,
    session: SessionDep,
    current_user: CurrentUser
) -> Message:
    """
    Delete an employee GitHub mapping.
    """
    mapping = session.get(EmployeeGitHubMapping, mapping_id)
    
    if not mapping:
        raise HTTPException(
            status_code=404,
            detail="Mapping not found"
        )
    
    session.delete(mapping)
    session.commit()
    
    return Message(message="GitHub mapping deleted successfully")


@router.post("/auto-map-employees")
async def auto_map_github_accounts(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Automatically map DarwinBox employees to GitHub accounts based on email matching.
    Requires superuser privileges.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Only superusers can perform auto-mapping"
        )
    
    try:
        result = await darwinbox_service.auto_map_github_accounts(
            session=session,
            current_user=current_user
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error auto-mapping GitHub accounts: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to auto-map accounts: {str(e)}"
        )


@router.post("/enhanced-auto-map")
async def enhanced_auto_map_employees(
    session: SessionDep,
    current_user: CurrentUser,
    confidence_threshold: float = Query(0.85, ge=0.0, le=1.0, description="Minimum confidence for auto-mapping (0-1)"),
    limit: int | None = Query(None, description="Maximum number of employees to process")
) -> Any:
    """
    Enhanced auto-mapping with advanced matching algorithms.
    Uses multiple strategies including fuzzy name matching, email normalization, and confidence scoring.
    Requires superuser privileges.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Only superusers can perform auto-mapping"
        )
    
    try:
        from app.services.enhanced_mapping_service import enhanced_mapping_service
        
        result = await enhanced_mapping_service.enhanced_auto_map(
            session=session,
            current_user=current_user,
            confidence_threshold=confidence_threshold,
            limit=limit
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error in enhanced auto-mapping: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to perform enhanced auto-mapping: {str(e)}"
        )


@router.post("/batch-review-mappings", response_model=BatchMappingReviewResponse)
def batch_review_mappings(
    review_data: BatchMappingReview,
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Batch review and approve/reject multiple mapping suggestions.
    Allows efficient processing of mapping recommendations from enhanced auto-mapping.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="Only superusers can review mappings"
        )
    
    approved = 0
    rejected = 0
    skipped = 0
    errors = []
    
    for mapping_item in review_data.mappings:
        try:
            if mapping_item.action == "skip":
                skipped += 1
                continue
            
            # Get employee
            employee = session.get(DarwinBoxEmployee, mapping_item.darwinbox_employee_id)
            if not employee:
                errors.append({
                    "employee_id": str(mapping_item.darwinbox_employee_id),
                    "error": "Employee not found"
                })
                continue
            
            if mapping_item.action == "approve":
                # Check if mapping already exists
                existing = session.exec(
                    select(EmployeeGitHubMapping)
                    .where(EmployeeGitHubMapping.darwinbox_employee_id == employee.id)
                ).first()
                
                if existing:
                    errors.append({
                        "employee_id": str(mapping_item.darwinbox_employee_id),
                        "error": "Mapping already exists"
                    })
                    continue
                
                # Get GitHub contributor
                contributor = session.exec(
                    select(GitHubContributor)
                    .where(GitHubContributor.login == mapping_item.github_username)
                ).first()
                
                if not contributor:
                    errors.append({
                        "employee_id": str(mapping_item.darwinbox_employee_id),
                        "error": f"GitHub user {mapping_item.github_username} not found"
                    })
                    continue
                
                # Create mapping
                new_mapping = EmployeeGitHubMapping(
                    darwinbox_employee_id=employee.id,
                    github_username=contributor.login,
                    github_id=contributor.github_id,
                    mapping_verified=review_data.auto_verify,
                    verification_method="manual_review",
                    verification_notes=mapping_item.notes or "Approved via batch review",
                    created_at=datetime.utcnow().isoformat(),
                    updated_at=datetime.utcnow().isoformat(),
                    mapped_by_id=current_user.id
                )
                session.add(new_mapping)
                approved += 1
                
            elif mapping_item.action == "reject":
                # Optionally store rejection reason for future reference
                # For now, just count it
                rejected += 1
                
        except Exception as e:
            errors.append({
                "employee_id": str(mapping_item.darwinbox_employee_id),
                "error": str(e)
            })
    
    session.commit()
    
    return BatchMappingReviewResponse(
        total_reviewed=len(review_data.mappings),
        approved=approved,
        rejected=rejected,
        skipped=skipped,
        errors=errors
    )


@router.get("/my-team")
def get_my_team(
    session: SessionDep,
    current_user: CurrentUser,
    include_skills: bool = True
) -> Any:
    """
    Get the current user's team based on DarwinBox hierarchy.
    User must be mapped to a DarwinBox employee who is a manager.
    """
    # Find if current user is mapped to a DarwinBox employee
    darwinbox_employee = None
    
    # First check if user has GitHub OAuth
    github_oauth = session.exec(
        select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    ).first()
    
    if github_oauth:
        # Check if there's a mapping via GitHub username
        mapping = session.exec(
            select(EmployeeGitHubMapping).where(
                EmployeeGitHubMapping.github_username == github_oauth.github_username
            )
        ).first()
        
        if mapping:
            darwinbox_employee = mapping.darwinbox_employee
    
    # If not found via GitHub, check by email
    if not darwinbox_employee:
        darwinbox_employee = session.exec(
            select(DarwinBoxEmployee).where(
                DarwinBoxEmployee.email == current_user.email
            )
        ).first()
    
    if not darwinbox_employee:
        raise HTTPException(
            status_code=404,
            detail="You are not mapped to a DarwinBox employee. Please contact an admin."
        )
    
    if not darwinbox_employee.is_manager:
        raise HTTPException(
            status_code=403,
            detail="You are not registered as a manager in DarwinBox"
        )
    
    try:
        team_data = darwinbox_service.get_team_hierarchy(
            session=session,
            manager_id=darwinbox_employee.darwinbox_id,
            include_skills=include_skills
        )
        
        return team_data
        
    except Exception as e:
        logger.error(f"Error getting team data: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get team data: {str(e)}"
        )


@router.get("/team/{manager_darwinbox_id}")
def get_team_by_manager_id(
    manager_darwinbox_id: str,
    session: SessionDep,
    current_user: CurrentUser,
    include_skills: bool = True
) -> Any:
    """
    Get team hierarchy for a specific manager by their DarwinBox ID.
    """
    try:
        team_data = darwinbox_service.get_team_hierarchy(
            session=session,
            manager_id=manager_darwinbox_id,
            include_skills=include_skills
        )
        
        return team_data
        
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting team data for manager {manager_darwinbox_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get team data: {str(e)}"
        )


@router.get("/departments")
def get_departments(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Get list of all departments in DarwinBox.
    """
    # Get unique departments
    departments_query = (
        select(DarwinBoxEmployee.department, func.count(DarwinBoxEmployee.id))
        .where(DarwinBoxEmployee.department != None)
        .group_by(DarwinBoxEmployee.department)
        .order_by(DarwinBoxEmployee.department)
    )
    
    departments = session.exec(departments_query).all()
    
    return {
        "departments": [
            {
                "name": dept[0],
                "employee_count": dept[1]
            }
            for dept in departments if dept[0]
        ],
        "total_count": len(departments)
    }


@router.get("/locations")
def get_locations(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Get list of all locations in DarwinBox.
    """
    # Get unique locations
    locations_query = (
        select(DarwinBoxEmployee.location, func.count(DarwinBoxEmployee.id))
        .where(DarwinBoxEmployee.location != None)
        .group_by(DarwinBoxEmployee.location)
        .order_by(DarwinBoxEmployee.location)
    )
    
    locations = session.exec(locations_query).all()
    
    return {
        "locations": [
            {
                "name": loc[0],
                "employee_count": loc[1]
            }
            for loc in locations if loc[0]
        ],
        "total_count": len(locations)
    }



@router.get("/stats")
def get_darwinbox_stats(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Get DarwinBox integration statistics.
    """
    # Total employees
    total_employees = session.exec(
        select(func.count(DarwinBoxEmployee.id))
    ).one()
    
    # Active employees
    active_employees = session.exec(
        select(func.count(DarwinBoxEmployee.id))
        .where(DarwinBoxEmployee.employment_status == "active")
    ).one()
    
    # Employees with GitHub mapping
    mapped_employees = session.exec(
        select(func.count(DarwinBoxEmployee.id))
        .where(DarwinBoxEmployee.github_mapping != None)
    ).one()
    
    # Managers
    managers = session.exec(
        select(func.count(DarwinBoxEmployee.id))
        .where(DarwinBoxEmployee.is_manager == True)
    ).one()
    
    # Department count
    departments = session.exec(
        select(func.count(func.distinct(DarwinBoxEmployee.department)))
        .where(DarwinBoxEmployee.department != None)
    ).one()
    
    # Location count
    locations = session.exec(
        select(func.count(func.distinct(DarwinBoxEmployee.location)))
        .where(DarwinBoxEmployee.location != None)
    ).one()
    
    # Last sync info
    last_sync = session.exec(
        select(DarwinBoxEmployee.last_sync_at)
        .order_by(DarwinBoxEmployee.last_sync_at.desc())
        .limit(1)
    ).first()
    
    return {
        "total_employees": total_employees,
        "active_employees": active_employees,
        "inactive_employees": total_employees - active_employees,
        "employees_with_github_mapping": mapped_employees,
        "employees_without_github_mapping": total_employees - mapped_employees,
        "github_mapping_percentage": (mapped_employees / total_employees * 100) if total_employees > 0 else 0,
        "total_managers": managers,
        "total_departments": departments,
        "total_locations": locations,
        "last_sync_at": last_sync if last_sync else None
    }


# Import required for type checking
from datetime import datetime
import httpx
import base64