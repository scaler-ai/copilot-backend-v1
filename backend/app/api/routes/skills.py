"""
Skill Mapping API Routes

Provides endpoints for skill taxonomy management, user skills, endorsements,
assessments, and skill gap analysis.
"""

import logging
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Depends
from sqlmodel import Session, select, func, and_

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    User,
    UserSkill,
    UserSkillCreate,
    UserSkillUpdate,
    UserSkillPublic,
    UserSkillsResponse,
    SkillEndorsement,
    SkillEndorsementCreate,
    SkillEndorsementPublic,
    SkillAssessment,
    SkillAssessmentCreate,
    SkillAssessmentPublic,
    SkillRequirement,
    SkillRequirementCreate,
    SkillRequirementPublic,
    SkillTaxonomyResponse,
    SkillAnalyticsResponse,
    SkillGap,
    SkillMatchResult,
    Message,
)
from app.services.skill_service import get_skill_taxonomy_service, validate_skill_exists, get_skill_name

logger = logging.getLogger(__name__)
router = APIRouter()


# Skill Taxonomy Endpoints
@router.get("/taxonomy", response_model=SkillTaxonomyResponse)
def get_skill_taxonomy(
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Get the complete skills taxonomy.
    """
    return skill_service.get_taxonomy_response()


@router.post("/taxonomy/reload", response_model=SkillTaxonomyResponse)
def reload_skill_taxonomy(
    current_user: CurrentUser,
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Reload the skills taxonomy from file (admin only).
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    try:
        skill_service.reload_taxonomy()
        logger.info(f"Skills taxonomy reloaded by user {current_user.id}")
        return skill_service.get_taxonomy_response()
    except Exception as e:
        logger.error(f"Error reloading taxonomy: {e}")
        raise HTTPException(status_code=500, detail=f"Error reloading taxonomy: {str(e)}")


@router.get("/taxonomy/search")
def search_skills(
    q: str = Query(..., min_length=2, description="Search query"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=100, description="Maximum results"),
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Search for skills in the taxonomy.
    """
    try:
        results = skill_service.search_skills(q, category, limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Error searching skills: {e}")
        raise HTTPException(status_code=500, detail="Error searching skills")


@router.get("/taxonomy/categories/{category}")
def get_skills_by_category(
    category: str,
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Get all skills in a specific category.
    """
    try:
        skills = skill_service.get_skills_by_category(category)
        return {"category": category, "skills": skills, "count": len(skills)}
    except Exception as e:
        logger.error(f"Error getting skills for category {category}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving skills")


@router.get("/taxonomy/pathways")
def get_skill_pathways(
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Get all skill learning pathways.
    """
    try:
        pathways = skill_service.get_skill_pathways()
        return {"pathways": pathways}
    except Exception as e:
        logger.error(f"Error getting skill pathways: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving pathways")


@router.get("/taxonomy/sfia-info")
def get_sfia_info(
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Get SFIA framework information and compliance status.
    """
    try:
        taxonomy = skill_service.load_taxonomy()
        is_sfia = skill_service.is_sfia_based()
        
        sfia_info = {
            "is_sfia_based": is_sfia,
            "framework_source": taxonomy.get('framework_source', ''),
            "framework_url": taxonomy.get('framework_url', ''),
            "version": taxonomy.get('version', ''),
            "schema_version": taxonomy.get('schema_version', '')
        }
        
        if is_sfia:
            # Add SFIA-specific statistics
            custom_mappings = taxonomy.get('custom_skill_mappings', {})
            sfia_info.update({
                "sfia_categories": len(taxonomy.get('categories', {})),
                "custom_skill_mappings": len(custom_mappings),
                "validation_rules": taxonomy.get('validation_rules', {})
            })
        
        return sfia_info
    except Exception as e:
        logger.error(f"Error getting SFIA info: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving SFIA information")


@router.get("/taxonomy/sfia/{sfia_code}")
def get_skills_by_sfia_code(
    sfia_code: str,
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Get all skills that map to a specific SFIA code.
    """
    try:
        skills = skill_service.get_skills_by_sfia_code(sfia_code.upper())
        return {
            "sfia_code": sfia_code.upper(),
            "skills": skills,
            "count": len(skills)
        }
    except Exception as e:
        logger.error(f"Error getting skills for SFIA code {sfia_code}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving skills")


@router.post("/taxonomy/validate-sfia")
def validate_sfia_compliance(
    current_user: CurrentUser,
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Validate SFIA compliance of the current taxonomy (admin only).
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    try:
        # This would ideally run the validation script
        # For now, return basic compliance information
        taxonomy = skill_service.load_taxonomy()
        is_sfia = skill_service.is_sfia_based()
        
        if not is_sfia:
            return {
                "compliant": False,
                "message": "Taxonomy is not SFIA-based",
                "recommendations": ["Consider migrating to SFIA-based taxonomy"]
            }
        
        # Basic compliance checks
        categories = taxonomy.get('categories', {})
        skill_levels = taxonomy.get('skill_levels', {})
        
        sfia_categories = {
            "strategy_and_architecture", "change_and_transformation",
            "development_and_implementation", "delivery_and_operation", 
            "people_and_skills", "relationships_and_engagement"
        }
        
        missing_categories = sfia_categories - set(categories.keys())
        has_7_levels = len(skill_levels) == 7
        
        compliance_score = 100
        issues = []
        
        if missing_categories:
            compliance_score -= 20
            issues.append(f"Missing SFIA categories: {list(missing_categories)}")
        
        if not has_7_levels:
            compliance_score -= 15
            issues.append(f"Should have 7 SFIA levels, found {len(skill_levels)}")
        
        return {
            "compliant": compliance_score >= 80,
            "compliance_score": compliance_score,
            "issues": issues,
            "sfia_categories_present": len(categories),
            "sfia_categories_total": 6,
            "skill_levels_present": len(skill_levels),
            "skill_levels_expected": 7
        }
        
    except Exception as e:
        logger.error(f"Error validating SFIA compliance: {e}")
        raise HTTPException(status_code=500, detail="Error validating SFIA compliance")


# User Skills Endpoints
@router.get("/my-skills", response_model=UserSkillsResponse)
def get_my_skills(
    session: SessionDep,
    current_user: CurrentUser,
    category: Optional[str] = Query(None, description="Filter by category"),
    level: Optional[str] = Query(None, description="Filter by skill level"),
    learning_status: Optional[str] = Query(None, description="Filter by learning status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
) -> Any:
    """
    Get current user's skills with optional filtering.
    """
    # Build query with filters
    query = select(UserSkill).where(UserSkill.owner_id == current_user.id)
    
    if level:
        query = query.where(UserSkill.skill_level == level)
    
    if learning_status:
        query = query.where(UserSkill.learning_status == learning_status)
    
    # Apply pagination
    query = query.offset(offset).limit(limit)
    
    skills = session.exec(query).all()
    
    # Get total count
    count_query = select(func.count(UserSkill.id)).where(UserSkill.owner_id == current_user.id)
    total_count = session.exec(count_query).first() or 0
    
    # Convert to public models with additional data
    skill_service = get_skill_taxonomy_service()
    public_skills = []
    
    for skill in skills:
        # Filter by category if specified
        if category:
            skill_info = skill_service.get_skill_by_id(skill.skill_id)
            if not skill_info or skill_info.get('category') != category:
                continue
        
        # Get endorsement count
        endorsement_count = session.exec(
            select(func.count(SkillEndorsement.id)).where(
                SkillEndorsement.user_skill_id == skill.id
            )
        ).first() or 0
        
        # Get latest assessment score
        latest_assessment = session.exec(
            select(SkillAssessment.score)
            .where(SkillAssessment.user_skill_id == skill.id)
            .order_by(SkillAssessment.created_at.desc())
            .limit(1)
        ).first()
        
        public_skill = UserSkillPublic(
            **skill.model_dump(),
            endorsement_count=endorsement_count,
            latest_assessment_score=latest_assessment
        )
        public_skills.append(public_skill)
    
    # Calculate statistics
    by_category = {}
    by_level = {}
    
    for skill in public_skills:
        skill_info = skill_service.get_skill_by_id(skill.skill_id)
        if skill_info:
            category_name = skill_info.get('category', 'unknown')
            by_category[category_name] = by_category.get(category_name, 0) + 1
        
        by_level[skill.skill_level] = by_level.get(skill.skill_level, 0) + 1
    
    return UserSkillsResponse(
        skills=public_skills,
        total_count=len(public_skills),
        by_category=by_category,
        by_level=by_level
    )


@router.post("/my-skills", response_model=UserSkillPublic)
def add_my_skill(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skill_data: UserSkillCreate,
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Add a new skill to current user's profile.
    """
    # Validate skill exists in taxonomy
    if not validate_skill_exists(skill_data.skill_id):
        raise HTTPException(status_code=400, detail="Skill not found in taxonomy")
    
    # Validate skill level is supported
    if not skill_service.validate_skill_level(skill_data.skill_id, skill_data.skill_level):
        raise HTTPException(status_code=400, detail="Skill level not supported for this skill")
    
    # Check if user already has this skill
    existing_skill = session.exec(
        select(UserSkill).where(
            and_(
                UserSkill.owner_id == current_user.id,
                UserSkill.skill_id == skill_data.skill_id
            )
        )
    ).first()
    
    if existing_skill:
        raise HTTPException(status_code=400, detail="Skill already exists for user")
    
    # Get skill name from taxonomy
    skill_name = get_skill_name(skill_data.skill_id)
    
    # Create new user skill
    db_skill = UserSkill(
        **skill_data.model_dump(),
        skill_name=skill_name,
        owner_id=current_user.id
    )
    
    session.add(db_skill)
    session.commit()
    session.refresh(db_skill)
    
    logger.info(f"User {current_user.id} added skill {skill_data.skill_id}")
    
    return UserSkillPublic(**db_skill.model_dump(), endorsement_count=0, latest_assessment_score=None)


@router.put("/my-skills/{skill_id}", response_model=UserSkillPublic)
def update_my_skill(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skill_id: UUID,
    skill_data: UserSkillUpdate,
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Update an existing skill in current user's profile.
    """
    # Get existing skill
    skill = session.exec(
        select(UserSkill).where(
            and_(
                UserSkill.id == skill_id,
                UserSkill.owner_id == current_user.id
            )
        )
    ).first()
    
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    # Validate new skill level if provided
    if skill_data.skill_level and not skill_service.validate_skill_level(skill.skill_id, skill_data.skill_level):
        raise HTTPException(status_code=400, detail="Skill level not supported for this skill")
    
    # Update skill
    update_data = skill_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(skill, field, value)
    
    skill.updated_at = datetime.utcnow().isoformat()
    
    session.add(skill)
    session.commit()
    session.refresh(skill)
    
    logger.info(f"User {current_user.id} updated skill {skill.skill_id}")
    
    return UserSkillPublic(**skill.model_dump(), endorsement_count=0, latest_assessment_score=None)


@router.delete("/my-skills/{skill_id}")
def delete_my_skill(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skill_id: UUID
) -> Message:
    """
    Delete a skill from current user's profile.
    """
    skill = session.exec(
        select(UserSkill).where(
            and_(
                UserSkill.id == skill_id,
                UserSkill.owner_id == current_user.id
            )
        )
    ).first()
    
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    session.delete(skill)
    session.commit()
    
    logger.info(f"User {current_user.id} deleted skill {skill.skill_id}")
    
    return Message(message="Skill deleted successfully")


# Skill Endorsements
@router.post("/endorsements", response_model=SkillEndorsementPublic)
def create_skill_endorsement(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    endorsement_data: SkillEndorsementCreate
) -> Any:
    """
    Endorse another user's skill.
    """
    # Get the user skill being endorsed
    user_skill = session.exec(
        select(UserSkill).where(UserSkill.id == endorsement_data.user_skill_id)
    ).first()
    
    if not user_skill:
        raise HTTPException(status_code=404, detail="User skill not found")
    
    # Can't endorse your own skills
    if user_skill.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot endorse your own skills")
    
    # Check if already endorsed
    existing_endorsement = session.exec(
        select(SkillEndorsement).where(
            and_(
                SkillEndorsement.user_skill_id == endorsement_data.user_skill_id,
                SkillEndorsement.endorsed_by_id == current_user.id
            )
        )
    ).first()
    
    if existing_endorsement:
        raise HTTPException(status_code=400, detail="Already endorsed this skill")
    
    # Create endorsement
    db_endorsement = SkillEndorsement(
        **endorsement_data.model_dump(),
        endorsed_by_id=current_user.id
    )
    
    session.add(db_endorsement)
    session.commit()
    session.refresh(db_endorsement)
    
    logger.info(f"User {current_user.id} endorsed skill {user_skill.skill_id} of user {user_skill.owner_id}")
    
    return SkillEndorsementPublic(
        **db_endorsement.model_dump(),
        endorsed_by_name=current_user.full_name or current_user.email,
        endorsed_by_id=current_user.id
    )


@router.get("/skills/{skill_id}/endorsements")
def get_skill_endorsements(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    skill_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
) -> Any:
    """
    Get endorsements for a specific user skill.
    """
    # Verify skill exists and belongs to current user
    user_skill = session.exec(
        select(UserSkill).where(
            and_(
                UserSkill.id == skill_id,
                UserSkill.owner_id == current_user.id
            )
        )
    ).first()
    
    if not user_skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    
    # Get endorsements with endorser info
    query = (
        select(SkillEndorsement, User.full_name, User.email)
        .join(User, SkillEndorsement.endorsed_by_id == User.id)
        .where(SkillEndorsement.user_skill_id == skill_id)
        .offset(offset)
        .limit(limit)
    )
    
    results = session.exec(query).all()
    
    endorsements = []
    for endorsement, full_name, email in results:
        endorsements.append(
            SkillEndorsementPublic(
                **endorsement.model_dump(),
                endorsed_by_name=full_name or email,
                endorsed_by_id=endorsement.endorsed_by_id
            )
        )
    
    return {"endorsements": endorsements, "count": len(endorsements)}


# Skill Assessments
@router.post("/assessments", response_model=SkillAssessmentPublic)
def create_skill_assessment(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    assessment_data: SkillAssessmentCreate
) -> Any:
    """
    Create a skill assessment.
    """
    # Get the user skill being assessed
    user_skill = session.exec(
        select(UserSkill).where(UserSkill.id == assessment_data.user_skill_id)
    ).first()
    
    if not user_skill:
        raise HTTPException(status_code=404, detail="User skill not found")
    
    # Determine assessor based on assessment type
    assessor_id = None
    if assessment_data.assessment_type == "self":
        # Self-assessment - must be skill owner
        if user_skill.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Can only self-assess your own skills")
        assessor_id = current_user.id
    else:
        # External assessment - assessor is current user
        assessor_id = current_user.id
    
    # Create assessment
    db_assessment = SkillAssessment(
        **assessment_data.model_dump(),
        assessor_id=assessor_id
    )
    
    session.add(db_assessment)
    session.commit()
    session.refresh(db_assessment)
    
    logger.info(f"Assessment created for skill {user_skill.skill_id} by user {current_user.id}")
    
    return SkillAssessmentPublic(
        **db_assessment.model_dump(),
        assessor_name=current_user.full_name or current_user.email
    )


# Skill Analytics and Matching
@router.get("/analytics", response_model=SkillAnalyticsResponse)
def get_skill_analytics(
    session: SessionDep,
    current_user: CurrentUser,
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Get skill analytics for the organization (admin only).
    """
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # Get all user skills
    all_skills = session.exec(select(UserSkill)).all()
    
    # Calculate statistics
    total_skills = len(all_skills)
    skills_by_category = {}
    skills_by_level = {}
    skill_counts = {}
    
    for skill in all_skills:
        # Category breakdown
        skill_info = skill_service.get_skill_by_id(skill.skill_id)
        if skill_info:
            category = skill_info.get('category', 'unknown')
            skills_by_category[category] = skills_by_category.get(category, 0) + 1
        
        # Level breakdown
        skills_by_level[skill.skill_level] = skills_by_level.get(skill.skill_level, 0) + 1
        
        # Skill popularity
        skill_counts[skill.skill_id] = skill_counts.get(skill.skill_id, 0) + 1
    
    # Top skills
    top_skills = [
        {"skill_id": skill_id, "skill_name": get_skill_name(skill_id), "count": count}
        for skill_id, count in sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ]
    
    return SkillAnalyticsResponse(
        total_skills=total_skills,
        skills_by_category=skills_by_category,
        skills_by_level=skills_by_level,
        top_skills=top_skills,
        skill_trends=[],  # TODO: Implement trend analysis
        certification_stats={}  # TODO: Implement certification stats
    )


@router.post("/gap-analysis")
def analyze_skill_gaps(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    required_skills: List[dict],
    skill_service = Depends(get_skill_taxonomy_service)
) -> Any:
    """
    Analyze skill gaps for current user against requirements.
    """
    # Get user's skills
    user_skills = session.exec(
        select(UserSkill).where(UserSkill.owner_id == current_user.id)
    ).all()
    
    # Perform gap analysis
    gaps = skill_service.analyze_skill_gaps(user_skills, required_skills)
    
    # Calculate overall match score
    match_score = skill_service.calculate_skill_match_score(user_skills, required_skills)
    
    return {
        "gaps": [gap.model_dump() for gap in gaps],
        "match_score": match_score,
        "total_requirements": len(required_skills),
        "critical_gaps": len([g for g in gaps if g.gap_severity == "critical"]),
        "major_gaps": len([g for g in gaps if g.gap_severity == "major"]),
        "minor_gaps": len([g for g in gaps if g.gap_severity == "minor"])
    }