"""
GitHub OAuth Integration API Routes
"""
import secrets
import httpx
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select, func

logger = logging.getLogger(__name__)

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.encryption import encryption_service
from app.models import (
    GitHubOAuth,
    GitHubOAuthCallback,
    GitHubOAuthPublic,
    GitHubOAuthResponse,
    GitHubOrganization,
    GitHubOrganizationPublic,
    GitHubContributor,
    GitHubContributorPublic,
    GitHubRepositoryContribution,
    GitHubOrganizationContributorsResponse,
    ContributorAnalysis,
    Message,
)
from app.services.github_analysis_service import github_analysis_service

router = APIRouter()

# GitHub OAuth Configuration
GITHUB_CLIENT_ID = settings.GITHUB_CLIENT_ID
GITHUB_CLIENT_SECRET = settings.GITHUB_CLIENT_SECRET
GITHUB_REDIRECT_URI = settings.GITHUB_REDIRECT_URI

# Required scopes for comprehensive repository access
GITHUB_SCOPES = [
    "repo",              # Full control of private repositories
    "read:user",         # Read user profile data
    "user:email",        # Access user email addresses
    "read:org",          # Read organization membership
    "read:discussion",   # Read discussions
    "read:project",      # Read projects
]


@router.get("/status", response_model=GitHubOAuthPublic | None)
def get_github_oauth_status(
    session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get current user's GitHub OAuth connection status.
    """
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth:
        return None
    
    return GitHubOAuthPublic(
        id=github_oauth.id,
        github_id=github_oauth.github_id,
        github_username=github_oauth.github_username,
        avatar_url=github_oauth.avatar_url,
        email=github_oauth.email,
        name=github_oauth.name,
        company=github_oauth.company,
        location=github_oauth.location,
        bio=github_oauth.bio,
        public_repos=github_oauth.public_repos,
        followers=github_oauth.followers,
        following=github_oauth.following,
        scopes=github_oauth.scopes,
        is_active=github_oauth.is_active,
        created_at=github_oauth.created_at,
        updated_at=github_oauth.updated_at,
        last_sync_at=github_oauth.last_sync_at,
        owner_id=github_oauth.owner_id
    )


@router.get("/auth-url")
def get_github_auth_url(current_user: CurrentUser) -> Any:
    """
    Generate GitHub OAuth authorization URL.
    """
    if not GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=500, 
            detail="GitHub OAuth is not configured. Please set GITHUB_CLIENT_ID environment variable."
        )
    
    # Generate secure state parameter for CSRF protection
    state = secrets.token_urlsafe(32)
    
    # Store state in session/cache (for now, we'll include user_id in state)
    # In production, you should use a proper session store
    state_with_user = f"{current_user.id}:{state}"
    
    params = {
        "client_id": GITHUB_CLIENT_ID,
        "redirect_uri": GITHUB_REDIRECT_URI,
        "scope": " ".join(GITHUB_SCOPES),
        "state": state_with_user,
        "response_type": "code",
    }
    
    auth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    
    return {
        "auth_url": auth_url,
        "state": state_with_user,
        "scopes": GITHUB_SCOPES
    }


@router.post("/callback", response_model=GitHubOAuthResponse)
async def github_oauth_callback(
    *, session: SessionDep, current_user: CurrentUser, callback_data: GitHubOAuthCallback
) -> Any:
    """
    Handle GitHub OAuth callback and exchange code for access token.
    """
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth is not configured. Please set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET."
        )
    
    try:
        # Validate state parameter
        if callback_data.state:
            state_parts = callback_data.state.split(":", 1)
            if len(state_parts) != 2 or state_parts[0] != str(current_user.id):
                raise HTTPException(status_code=400, detail="Invalid state parameter")
        
        # Exchange authorization code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "code": callback_data.code,
                    "redirect_uri": GITHUB_REDIRECT_URI,
                }
            )
            token_response.raise_for_status()
            token_data = token_response.json()
        
        if "access_token" not in token_data:
            raise HTTPException(
                status_code=400, 
                detail=f"Failed to get access token: {token_data.get('error_description', 'Unknown error')}"
            )
        
        access_token = token_data["access_token"]
        scopes = token_data.get("scope", "").split(",") if token_data.get("scope") else GITHUB_SCOPES
        
        # Get user information from GitHub
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_response.raise_for_status()
            user_data = user_response.json()
        
        # Check if user already has GitHub OAuth connection
        existing_oauth = session.exec(
            select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
        ).first()
        
        # Encrypt access token
        encrypted_token = encryption_service.encrypt(access_token)
        
        now = datetime.utcnow().isoformat()
        
        if existing_oauth:
            # Update existing connection
            existing_oauth.github_id = user_data["id"]
            existing_oauth.github_username = user_data["login"]
            existing_oauth.avatar_url = user_data.get("avatar_url")
            existing_oauth.email = user_data.get("email")
            existing_oauth.name = user_data.get("name")
            existing_oauth.company = user_data.get("company")
            existing_oauth.location = user_data.get("location")
            existing_oauth.bio = user_data.get("bio")
            existing_oauth.public_repos = user_data.get("public_repos")
            existing_oauth.followers = user_data.get("followers")
            existing_oauth.following = user_data.get("following")
            existing_oauth.scopes = ",".join(scopes)
            existing_oauth.encrypted_access_token = encrypted_token
            existing_oauth.updated_at = now
            existing_oauth.last_sync_at = now
            existing_oauth.is_active = True
            
            session.add(existing_oauth)
            session.commit()
            session.refresh(existing_oauth)
            
            github_oauth = existing_oauth
        else:
            # Create new connection
            github_oauth = GitHubOAuth(
                github_id=user_data["id"],
                github_username=user_data["login"],
                avatar_url=user_data.get("avatar_url"),
                email=user_data.get("email"),
                name=user_data.get("name"),
                company=user_data.get("company"),
                location=user_data.get("location"),
                bio=user_data.get("bio"),
                public_repos=user_data.get("public_repos"),
                followers=user_data.get("followers"),
                following=user_data.get("following"),
                scopes=",".join(scopes),
                encrypted_access_token=encrypted_token,
                created_at=now,
                updated_at=now,
                last_sync_at=now,
                owner_id=current_user.id,
                is_active=True
            )
            
            session.add(github_oauth)
            session.commit()
            session.refresh(github_oauth)
        
        return GitHubOAuthResponse(
            success=True,
            message="GitHub account connected successfully",
            github_oauth=GitHubOAuthPublic(
                id=github_oauth.id,
                github_id=github_oauth.github_id,
                github_username=github_oauth.github_username,
                avatar_url=github_oauth.avatar_url,
                email=github_oauth.email,
                name=github_oauth.name,
                company=github_oauth.company,
                location=github_oauth.location,
                bio=github_oauth.bio,
                public_repos=github_oauth.public_repos,
                followers=github_oauth.followers,
                following=github_oauth.following,
                scopes=github_oauth.scopes,
                is_active=github_oauth.is_active,
                created_at=github_oauth.created_at,
                updated_at=github_oauth.updated_at,
                last_sync_at=github_oauth.last_sync_at,
                owner_id=github_oauth.owner_id
            )
        )
        
    except httpx.HTTPError as e:
        raise HTTPException(status_code=400, detail=f"GitHub API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OAuth callback failed: {str(e)}")


@router.delete("/disconnect")
def disconnect_github(
    session: SessionDep, current_user: CurrentUser
) -> Message:
    """
    Disconnect GitHub OAuth connection.
    """
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth:
        raise HTTPException(status_code=404, detail="GitHub connection not found")
    
    session.delete(github_oauth)
    session.commit()
    
    return Message(message="GitHub account disconnected successfully")


@router.post("/refresh")
async def refresh_github_connection(
    session: SessionDep, current_user: CurrentUser
) -> GitHubOAuthResponse:
    """
    Refresh GitHub user data and verify token validity.
    """
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth:
        raise HTTPException(status_code=404, detail="GitHub connection not found")
    
    try:
        # Decrypt access token
        access_token = encryption_service.decrypt(github_oauth.encrypted_access_token)
        
        # Test token and get fresh user data
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_response.raise_for_status()
            user_data = user_response.json()
        
        # Update user data
        github_oauth.github_username = user_data["login"]
        github_oauth.avatar_url = user_data.get("avatar_url")
        github_oauth.email = user_data.get("email")
        github_oauth.name = user_data.get("name")
        github_oauth.company = user_data.get("company")
        github_oauth.location = user_data.get("location")
        github_oauth.bio = user_data.get("bio")
        github_oauth.public_repos = user_data.get("public_repos")
        github_oauth.followers = user_data.get("followers")
        github_oauth.following = user_data.get("following")
        github_oauth.updated_at = datetime.utcnow().isoformat()
        github_oauth.last_sync_at = datetime.utcnow().isoformat()
        github_oauth.is_active = True
        
        session.add(github_oauth)
        session.commit()
        session.refresh(github_oauth)
        
        return GitHubOAuthResponse(
            success=True,
            message="GitHub connection refreshed successfully",
            github_oauth=GitHubOAuthPublic(
                id=github_oauth.id,
                github_id=github_oauth.github_id,
                github_username=github_oauth.github_username,
                avatar_url=github_oauth.avatar_url,
                email=github_oauth.email,
                name=github_oauth.name,
                company=github_oauth.company,
                location=github_oauth.location,
                bio=github_oauth.bio,
                public_repos=github_oauth.public_repos,
                followers=github_oauth.followers,
                following=github_oauth.following,
                scopes=github_oauth.scopes,
                is_active=github_oauth.is_active,
                created_at=github_oauth.created_at,
                updated_at=github_oauth.updated_at,
                last_sync_at=github_oauth.last_sync_at,
                owner_id=github_oauth.owner_id
            )
        )
        
    except httpx.HTTPError as e:
        # Token might be invalid, mark as inactive
        github_oauth.is_active = False
        github_oauth.updated_at = datetime.utcnow().isoformat()
        session.add(github_oauth)
        session.commit()
        
        raise HTTPException(
            status_code=401, 
            detail="GitHub token is invalid. Please reconnect your GitHub account."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh GitHub connection: {str(e)}")


@router.get("/org/{org_name}/contributors")
async def get_organization_contributors(
    org_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    per_page: int = 30,
    page: int = 1
) -> Any:
    """
    Get organization contributors from database.
    Returns contributors that have been synced using the save endpoint.
    """
    # Verify user has GitHub OAuth connection
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=401, 
            detail="GitHub connection required. Please connect your GitHub account first."
        )
    
    # Validate pagination parameters
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 30
    
    # Get organization from database
    org_statement = select(GitHubOrganization).where(GitHubOrganization.name == org_name)
    organization = session.exec(org_statement).first()
    
    if not organization:
        raise HTTPException(
            status_code=404,
            detail=f"Organization '{org_name}' not found in database. Please sync it first using POST /org/{org_name}/contributors/save"
        )
    
    # Get total count of contributors
    count_statement = select(func.count()).select_from(GitHubContributor).where(
        GitHubContributor.organization_id == organization.id
    )
    total_contributors = session.exec(count_statement).one()
    
    # Get paginated contributors with their repository contributions
    contributors_statement = (
        select(GitHubContributor)
        .where(GitHubContributor.organization_id == organization.id)
        .order_by(GitHubContributor.total_contributions.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    contributors = session.exec(contributors_statement).all()
    
    # Format response with repository contributions
    contributors_data = []
    for contributor in contributors:
        # Get repository contributions for this contributor
        repo_contributions_statement = (
            select(GitHubRepositoryContribution)
            .where(GitHubRepositoryContribution.contributor_id == contributor.id)
            .order_by(GitHubRepositoryContribution.contributions.desc())
        )
        repo_contributions = session.exec(repo_contributions_statement).all()
        
        repositories = []
        for repo_contrib in repo_contributions:
            repositories.append({
                "name": repo_contrib.repository_name,
                "contributions": repo_contrib.contributions,
                "html_url": repo_contrib.repository_url,
                "language": repo_contrib.repository_language,
                "stars": repo_contrib.repository_stars,
                "forks": repo_contrib.repository_forks
            })
        
        # Get latest analysis for this contributor
        latest_analysis_statement = select(ContributorAnalysis).where(
            ContributorAnalysis.contributor_id == contributor.id
        ).order_by(ContributorAnalysis.generated_at.desc()).limit(1)
        latest_analysis = session.exec(latest_analysis_statement).first()
        
        # Calculate total skills from latest analysis
        total_skills = 0
        if latest_analysis and latest_analysis.skill_inferences:
            try:
                skill_data = json.loads(latest_analysis.skill_inferences)
                total_skills = len(skill_data) if isinstance(skill_data, list) else 0
            except:
                total_skills = 0
        
        contributors_data.append({
            "id": str(contributor.id),  # UUID as string for JSON serialization
            "github_id": contributor.github_id,
            "login": contributor.login,
            "avatar_url": contributor.avatar_url,
            "html_url": contributor.html_url,
            "type": contributor.type,
            "site_admin": contributor.site_admin,
            "total_contributions": contributor.total_contributions,
            "last_sync_at": contributor.last_sync_at if contributor.last_sync_at else None,
            "repositories": repositories,
            "last_analyzed_at": latest_analysis.generated_at if latest_analysis else None,
            "analysis_summary": {
                "total_skills": total_skills,
                "confidence_score": latest_analysis.confidence_score if latest_analysis else None
            } if latest_analysis else None
        })
    
    # Get total repository count
    repo_count_statement = (
        select(func.count(func.distinct(GitHubRepositoryContribution.repository_name)))
        .select_from(GitHubRepositoryContribution)
        .join(GitHubContributor)
        .where(GitHubContributor.organization_id == organization.id)
    )
    total_repositories = session.exec(repo_count_statement).one()
    
    return {
        "organization": org_name,
        "organization_id": str(organization.id),
        "total_contributors": total_contributors,
        "total_repositories": total_repositories,
        "page": page,
        "per_page": per_page,
        "total_pages": (total_contributors + per_page - 1) // per_page,
        "last_sync_at": organization.last_sync_at if organization.last_sync_at else None,
        "contributors": contributors_data
    }


@router.post("/org/{org_name}/contributors/save")
async def save_organization_contributors(
    org_name: str,
    session: SessionDep,
    current_user: CurrentUser
) -> Message:
    """
    Fetch and save organization contributors to database.
    Requires GitHub OAuth connection with 'read:org' scope.
    """
    # Verify user has GitHub OAuth connection
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=401, 
            detail="GitHub connection required. Please connect your GitHub account first."
        )
    
    # Check if user has required scope
    scopes = github_oauth.scopes.split(",") if github_oauth.scopes else []
    if "read:org" not in scopes:
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions. 'read:org' scope required to access organization data."
        )
    
    try:
        # Decrypt access token
        access_token = encryption_service.decrypt(github_oauth.encrypted_access_token)
        
        async with httpx.AsyncClient() as client:
            # Get organization details
            org_response = await client.get(
                f"https://api.github.com/orgs/{org_name}",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            org_response.raise_for_status()
            org_data = org_response.json()
            
            # Check if organization already exists
            existing_org = session.exec(
                select(GitHubOrganization).where(GitHubOrganization.github_id == org_data["id"])
            ).first()
            
            now = datetime.utcnow().isoformat()
            
            if existing_org:
                # Update existing organization
                existing_org.name = org_data["login"]
                existing_org.description = org_data.get("description")
                existing_org.html_url = org_data["html_url"]
                existing_org.avatar_url = org_data.get("avatar_url")
                existing_org.public_repos = org_data.get("public_repos")
                existing_org.followers = org_data.get("followers")
                existing_org.following = org_data.get("following")
                existing_org.location = org_data.get("location")
                existing_org.email = org_data.get("email")
                existing_org.blog = org_data.get("blog")
                existing_org.company = org_data.get("company")
                existing_org.twitter_username = org_data.get("twitter_username")
                existing_org.updated_at = now
                existing_org.last_sync_at = now
                
                organization = existing_org
            else:
                # Create new organization
                organization = GitHubOrganization(
                    github_id=org_data["id"],
                    name=org_data["login"],
                    description=org_data.get("description"),
                    html_url=org_data["html_url"],
                    avatar_url=org_data.get("avatar_url"),
                    public_repos=org_data.get("public_repos"),
                    followers=org_data.get("followers"),
                    following=org_data.get("following"),
                    location=org_data.get("location"),
                    email=org_data.get("email"),
                    blog=org_data.get("blog"),
                    company=org_data.get("company"),
                    twitter_username=org_data.get("twitter_username"),
                    created_at=now,
                    updated_at=now,
                    last_sync_at=now,
                    discovered_by_id=current_user.id
                )
                session.add(organization)
            
            session.commit()
            session.refresh(organization)
            
            # Get all repositories in the organization
            repos_response = await client.get(
                f"https://api.github.com/orgs/{org_name}/repos",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"type": "all", "per_page": 100}
            )
            repos_response.raise_for_status()
            repositories = repos_response.json()
            
            # Collect and save all contributors
            contributors_saved = 0
            
            for repo in repositories:
                repo_name = repo["name"]
                contributors_url = f"https://api.github.com/repos/{org_name}/{repo_name}/contributors"
                
                try:
                    contributors_response = await client.get(
                        contributors_url,
                        headers={"Authorization": f"Bearer {access_token}"},
                        params={"per_page": 100}
                    )
                    contributors_response.raise_for_status()
                    contributors = contributors_response.json()
                    
                    for contributor_data in contributors:
                        # Check if contributor already exists for this organization
                        existing_contributor = session.exec(
                            select(GitHubContributor).where(
                                GitHubContributor.github_id == contributor_data["id"],
                                GitHubContributor.organization_id == organization.id
                            )
                        ).first()
                        
                        # Skip fetching detailed user information during bulk sync
                        # This will be done in a separate endpoint to avoid timeouts
                        user_details = {}
                        
                        if existing_contributor:
                            # Update existing contributor with enhanced data
                            existing_contributor.login = contributor_data["login"]
                            existing_contributor.avatar_url = contributor_data.get("avatar_url")
                            existing_contributor.html_url = contributor_data["html_url"]
                            existing_contributor.type = contributor_data.get("type", "User")
                            existing_contributor.site_admin = contributor_data.get("site_admin", False)
                            existing_contributor.updated_at = now
                            existing_contributor.last_sync_at = now
                            
                            # Update with detailed user information
                            for field, value in user_details.items():
                                if value is not None:
                                    setattr(existing_contributor, field, value)
                            
                            contributor = existing_contributor
                        else:
                            # Create new contributor with enhanced data
                            contributor = GitHubContributor(
                                github_id=contributor_data["id"],
                                login=contributor_data["login"],
                                avatar_url=contributor_data.get("avatar_url"),
                                html_url=contributor_data["html_url"],
                                type=contributor_data.get("type", "User"),
                                site_admin=contributor_data.get("site_admin", False),
                                created_at=now,
                                updated_at=now,
                                last_sync_at=now,
                                organization_id=organization.id,
                                total_contributions=0,
                                **user_details
                            )
                            session.add(contributor)
                            contributors_saved += 1
                        
                        session.commit()
                        session.refresh(contributor)
                        
                        # Save repository contribution data
                        existing_repo_contribution = session.exec(
                            select(GitHubRepositoryContribution).where(
                                GitHubRepositoryContribution.contributor_id == contributor.id,
                                GitHubRepositoryContribution.repository_name == repo_name
                            )
                        ).first()
                        
                        if existing_repo_contribution:
                            # Update existing contribution
                            existing_repo_contribution.contributions = contributor_data["contributions"]
                            existing_repo_contribution.repository_url = repo["html_url"]
                            existing_repo_contribution.repository_description = repo.get("description")
                            existing_repo_contribution.repository_language = repo.get("language")
                            existing_repo_contribution.repository_stars = repo.get("stargazers_count")
                            existing_repo_contribution.repository_forks = repo.get("forks_count")
                            existing_repo_contribution.is_fork = repo.get("fork", False)
                            existing_repo_contribution.is_private = repo.get("private", False)
                            existing_repo_contribution.updated_at = now
                        else:
                            # Create new contribution record
                            repo_contribution = GitHubRepositoryContribution(
                                repository_id=repo.get("id"),
                                repository_name=repo_name,
                                repository_url=repo["html_url"],
                                contributions=contributor_data["contributions"],
                                repository_description=repo.get("description"),
                                repository_language=repo.get("language"),
                                repository_stars=repo.get("stargazers_count"),
                                repository_forks=repo.get("forks_count"),
                                is_fork=repo.get("fork", False),
                                is_private=repo.get("private", False),
                                created_at=now,
                                updated_at=now,
                                contributor_id=contributor.id
                            )
                            session.add(repo_contribution)
                        
                        # Update contributor's total contributions
                        contributor.total_contributions += contributor_data["contributions"]
                        
                except httpx.HTTPError:
                    # Skip repositories where we can't access contributors
                    continue
            
            session.commit()
            
            return Message(
                message=f"Successfully saved {contributors_saved} contributors for organization '{org_name}'"
            )
            
    except httpx.HTTPError as e:
        if hasattr(e, 'response') and e.response and e.response.status_code == 404:
            raise HTTPException(
                status_code=404, 
                detail=f"Organization '{org_name}' not found or not accessible"
            )
        elif hasattr(e, 'response') and e.response and e.response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail="Access denied. You may not have permission to view this organization."
            )
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"GitHub API error: {str(e)}"
            )
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to save organization contributors: {str(e)}"
        )


@router.get("/contributor/{contributor_id}/detailed-activities")
async def get_contributor_detailed_activities(
    contributor_id: str,
    session: SessionDep,
    current_user: CurrentUser,
    months_back: int = 12
) -> Any:
    """
    Get detailed GitHub activities for a specific contributor for skill analysis.
    Requires GitHub OAuth connection with appropriate scopes.
    """
    # Verify user has GitHub OAuth connection
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=401, 
            detail="GitHub connection required. Please connect your GitHub account first."
        )
    
    try:
        # Get contributor details
        contributor_statement = select(GitHubContributor).where(GitHubContributor.id == contributor_id)
        contributor = session.exec(contributor_statement).first()
        
        if not contributor:
            raise HTTPException(status_code=404, detail="Contributor not found")
        
        # Collect detailed activities
        activity_data = await github_analysis_service.collect_contributor_activities(
            contributor, github_oauth, session, months_back
        )
        
        # Prepare response
        return {
            "contributor": {
                "id": contributor.id,
                "github_id": contributor.github_id,
                "login": contributor.login,
                "name": contributor.name,
                "total_contributions": contributor.total_contributions
            },
            "activity_summary": {
                "total_activities": activity_data.total_activities,
                "pull_requests_count": len(activity_data.pull_requests),
                "code_reviews_count": len(activity_data.code_reviews),
                "issues_count": len(activity_data.issues),
                "commits_count": len(activity_data.commits),
                "repositories_count": len(activity_data.repositories),
                "top_languages": dict(sorted(activity_data.languages.items(), key=lambda x: x[1], reverse=True)[:5])
            },
            "pull_requests": activity_data.pull_requests[:20],  # Limit to recent 20
            "code_reviews": activity_data.code_reviews[:20],
            "issues": activity_data.issues[:20],
            "commits": activity_data.commits[:20],
            "repositories": list(activity_data.repositories),
            "period_analyzed": f"{months_back} months",
            "analyzed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting detailed activities for contributor {contributor_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to collect contributor activities: {str(e)}"
        )


@router.post("/contributor/{contributor_id}/analyze-skills")
async def analyze_contributor_skills(
    contributor_id: str,
    session: SessionDep,
    current_user: CurrentUser,
    months_back: int = 12
) -> Any:
    """
    Analyze a contributor's GitHub activities to infer skills and career level.
    This generates an AI-powered assessment based on their contributions.
    """
    # Verify user has GitHub OAuth connection
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=401, 
            detail="GitHub connection required. Please connect your GitHub account first."
        )
    
    try:
        # Get contributor details
        contributor_statement = select(GitHubContributor).where(GitHubContributor.id == contributor_id)
        contributor = session.exec(contributor_statement).first()
        
        if not contributor:
            raise HTTPException(status_code=404, detail="Contributor not found")
        
        # Check if recent analysis exists
        existing_analysis = session.exec(
            select(ContributorAnalysis)
            .where(ContributorAnalysis.contributor_id == contributor_id)
            .order_by(ContributorAnalysis.generated_at.desc())
        ).first()
        
        # If analysis exists and is recent (less than 7 days), return it
        if existing_analysis:
            generated_date = datetime.fromisoformat(existing_analysis.generated_at)
            if datetime.utcnow() - generated_date < timedelta(days=7):
                # Parse skill inferences
                skill_inferences = []
                try:
                    if existing_analysis.skill_inferences:
                        skill_inferences = json.loads(existing_analysis.skill_inferences)
                except json.JSONDecodeError:
                    pass
                
                return {
                    "analysis": {
                        "id": existing_analysis.id,
                        "technical_summary": existing_analysis.technical_summary,
                        "career_level_assessment": existing_analysis.career_level_assessment,
                        "confidence_score": existing_analysis.confidence_score,
                        "total_activities_analyzed": existing_analysis.total_activities_analyzed,
                        "generated_at": existing_analysis.generated_at,
                        "skill_inferences": skill_inferences,
                        "is_recent": True
                    },
                    "contributor": {
                        "id": contributor.id,
                        "login": contributor.login,
                        "name": contributor.name
                    }
                }
        
        # Collect activities and generate new analysis
        activity_data = await github_analysis_service.collect_contributor_activities(
            contributor, github_oauth, session, months_back
        )
        
        # Generate comprehensive analysis
        analysis = await github_analysis_service.analyze_contributor_activities(
            contributor, activity_data, current_user, session
        )
        
        # Parse skill inferences
        skill_inferences = []
        try:
            if analysis.skill_inferences:
                skill_inferences = json.loads(analysis.skill_inferences)
        except json.JSONDecodeError:
            pass
        
        return {
            "analysis": {
                "id": analysis.id,
                "technical_summary": analysis.technical_summary,
                "career_level_assessment": analysis.career_level_assessment,
                "confidence_score": analysis.confidence_score,
                "total_activities_analyzed": analysis.total_activities_analyzed,
                "generated_at": analysis.generated_at,
                "skill_inferences": skill_inferences,
                "is_recent": False
            },
            "contributor": {
                "id": contributor.id,
                "login": contributor.login,
                "name": contributor.name
            },
            "activity_summary": {
                "total_activities": activity_data.total_activities,
                "repositories_count": len(activity_data.repositories),
                "top_languages": dict(sorted(activity_data.languages.items(), key=lambda x: x[1], reverse=True)[:5])
            }
        }
        
    except Exception as e:
        logger.error(f"Error analyzing skills for contributor {contributor_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze contributor skills: {str(e)}"
        )


@router.get("/my-github-analysis")
async def get_my_github_analysis(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Get the current user's own GitHub contribution analysis.
    Requires the user to be a contributor in at least one organization.
    """
    
    # Check if user has GitHub OAuth
    github_oauth_statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(github_oauth_statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=404, 
            detail="GitHub integration not found. Please connect your GitHub account first."
        )
    
    try:
        # Find contributor record for this user
        contributor_statement = select(GitHubContributor).where(
            GitHubContributor.github_id == github_oauth.github_id
        )
        contributor = session.exec(contributor_statement).first()
        
        if not contributor:
            return {
                "has_analysis": False,
                "message": "No contributor record found. You may need to be added to an organization first.",
                "github_username": github_oauth.github_username,
                "suggestion": "Ask an organization admin to sync contributors or join an organization."
            }
        
        # Get latest analysis
        analysis_statement = select(ContributorAnalysis).where(
            ContributorAnalysis.contributor_id == contributor.id
        ).order_by(ContributorAnalysis.generated_at.desc())
        latest_analysis = session.exec(analysis_statement).first()
        
        if not latest_analysis:
            return {
                "has_analysis": False,
                "contributor": {
                    "id": contributor.id,
                    "login": contributor.login,
                    "name": contributor.name,
                    "total_contributions": contributor.total_contributions
                },
                "message": "No skill analysis found. You can request a new analysis.",
                "can_analyze": True
            }
        
        # Parse skill inferences
        skill_inferences = []
        try:
            if latest_analysis.skill_inferences:
                skill_inferences = json.loads(latest_analysis.skill_inferences)
        except json.JSONDecodeError:
            pass
        
        # Parse strengths and improvement areas
        strengths = []
        improvement_areas = []
        try:
            if latest_analysis.strengths:
                strengths = json.loads(latest_analysis.strengths)
            if latest_analysis.improvement_areas:
                improvement_areas = json.loads(latest_analysis.improvement_areas)
        except json.JSONDecodeError:
            pass
        
        return {
            "has_analysis": True,
            "analysis": {
                "id": latest_analysis.id,
                "technical_summary": latest_analysis.technical_summary,
                "career_level_assessment": latest_analysis.career_level_assessment,
                "confidence_score": latest_analysis.confidence_score,
                "total_activities_analyzed": latest_analysis.total_activities_analyzed,
                "analysis_period_months": latest_analysis.analysis_period_months,
                "generated_at": latest_analysis.generated_at,
                "skill_inferences": skill_inferences,
                "strengths": strengths,
                "improvement_areas": improvement_areas
            },
            "contributor": {
                "id": contributor.id,
                "login": contributor.login,
                "name": contributor.name,
                "total_contributions": contributor.total_contributions
            },
            "can_refresh": True,
            "last_updated": latest_analysis.generated_at
        }
        
    except Exception as e:
        logger.error(f"Error getting GitHub analysis for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve GitHub analysis: {str(e)}"
        )


@router.post("/request-my-analysis")
async def request_my_github_analysis(
    session: SessionDep,
    current_user: CurrentUser,
    months_back: int = 12
) -> Message:
    """
    Request a fresh GitHub contribution analysis for the current user.
    This will analyze their recent activities and generate skill assessments.
    """
    from app.services.github_analysis_service import github_analysis_service
    
    # Check if user has GitHub OAuth
    github_oauth_statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(github_oauth_statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=404, 
            detail="GitHub integration not found. Please connect your GitHub account first."
        )
    
    try:
        # Find contributor record for this user
        contributor_statement = select(GitHubContributor).where(
            GitHubContributor.github_id == github_oauth.github_id
        )
        contributor = session.exec(contributor_statement).first()
        
        if not contributor:
            raise HTTPException(
                status_code=404,
                detail="No contributor record found. You may need to be added to an organization first."
            )
        
        # Collect activities and generate analysis
        activity_data = await github_analysis_service.collect_contributor_activities(
            contributor, github_oauth, session, months_back
        )
        
        # Generate comprehensive analysis
        analysis = await github_analysis_service.analyze_contributor_activities(
            contributor, activity_data, current_user, session
        )
        
        return Message(
            message=f"GitHub analysis completed successfully. Analyzed {activity_data.total_activities} "
                   f"activities across {len(activity_data.repositories)} repositories over the past {months_back} months."
        )
        
    except Exception as e:
        logger.error(f"Error requesting GitHub analysis for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate GitHub analysis: {str(e)}"
        )


@router.get("/user/orgs")
async def get_user_organizations(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Get the current user's GitHub organizations from the database.
    Returns organizations where the user is a contributor.
    """
    
    # Verify user has GitHub OAuth connection
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=401, 
            detail="GitHub connection required. Please connect your GitHub account first."
        )
    
    try:
        # Find all organizations where this user is a contributor
        organizations_statement = (
            select(GitHubOrganization)
            .join(GitHubContributor)
            .where(GitHubContributor.github_id == github_oauth.github_id)
            .distinct()
        )
        organizations = session.exec(organizations_statement).all()
        
        # Format the response
        organizations_data = []
        for org in organizations:
            organizations_data.append({
                "id": org.github_id,
                "login": org.name,
                "name": org.name,
                "description": org.description,
                "avatar_url": org.avatar_url,
                "html_url": org.html_url,
                "public_repos": org.public_repos,
                "followers": org.followers,
                "following": org.following,
                "location": org.location,
                "blog": org.blog,
                "email": org.email,
                "company": org.company,
                "twitter_username": org.twitter_username,
                "last_sync_at": org.last_sync_at,
                "in_database": True
            })
        
        return {
            "organizations": organizations_data,
            "total_count": len(organizations_data),
            "user": {
                "github_username": github_oauth.github_username,
                "github_id": github_oauth.github_id
            },
            "source": "database",
            "note": "Showing organizations where you are a contributor. Use the save endpoint to sync new organizations."
        }
        
    except Exception as e:
        logger.error(f"Error getting user organizations from database: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get user organizations: {str(e)}"
        )


@router.post("/org/{org_name}/contributors/fetch-emails")
async def fetch_contributor_emails(
    org_name: str,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = 100
) -> Message:
    """
    Bulk fetch email addresses for contributors in an organization using GitHub GraphQL API.
    This is much more efficient than individual REST API calls.
    """
    # Verify user has GitHub OAuth connection
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=401, 
            detail="GitHub connection required. Please connect your GitHub account first."
        )
    
    try:
        # Decrypt access token
        access_token = encryption_service.decrypt(github_oauth.encrypted_access_token)
        
        # Get organization
        org_statement = select(GitHubOrganization).where(GitHubOrganization.name == org_name)
        organization = session.exec(org_statement).first()
        
        if not organization:
            raise HTTPException(
                status_code=404,
                detail=f"Organization '{org_name}' not found. Please sync it first."
            )
        
        # Get contributors without email addresses
        contributors_without_email = session.exec(
            select(GitHubContributor)
            .where(GitHubContributor.organization_id == organization.id)
            .where(GitHubContributor.email == None)
            .limit(limit)
        ).all()
        
        if not contributors_without_email:
            return Message(message="All contributors already have email addresses fetched.")
        
        updated_count = 0
        
        async with httpx.AsyncClient() as client:
            # Process contributors in batches of 50 using GraphQL
            batch_size = 50
            for i in range(0, len(contributors_without_email), batch_size):
                batch = contributors_without_email[i:i + batch_size]
                
                # Build GraphQL query for batch
                user_queries = []
                for idx, contributor in enumerate(batch):
                    user_queries.append(f'''
                        user{idx}: user(login: "{contributor.login}") {{
                            login
                            email
                            name
                            company
                            bio
                            location
                            websiteUrl
                            isHireable
                            followers {{ totalCount }}
                            following {{ totalCount }}
                            repositories(privacy: PUBLIC) {{ totalCount }}
                        }}
                    ''')
                
                graphql_query = f'''
                    query {{
                        {" ".join(user_queries)}
                    }}
                '''
                
                try:
                    # Make GraphQL request
                    response = await client.post(
                        "https://api.github.com/graphql",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json"
                        },
                        json={"query": graphql_query},
                        timeout=30.0
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        
                        if "data" in data:
                            # Update contributors with fetched data
                            for idx, contributor in enumerate(batch):
                                user_key = f"user{idx}"
                                if user_key in data["data"] and data["data"][user_key]:
                                    user_data = data["data"][user_key]
                                    
                                    # Update contributor with detailed information
                                    contributor.email = user_data.get("email")
                                    contributor.name = user_data.get("name")
                                    contributor.company = user_data.get("company")
                                    contributor.bio = user_data.get("bio")
                                    contributor.location = user_data.get("location")
                                    contributor.blog = user_data.get("websiteUrl")
                                    contributor.hireable = user_data.get("isHireable")
                                    
                                    # Update counts from GraphQL response
                                    if "followers" in user_data and user_data["followers"]:
                                        contributor.followers = user_data["followers"]["totalCount"]
                                    if "following" in user_data and user_data["following"]:
                                        contributor.following = user_data["following"]["totalCount"]
                                    if "repositories" in user_data and user_data["repositories"]:
                                        contributor.public_repos = user_data["repositories"]["totalCount"]
                                    
                                    contributor.updated_at = datetime.utcnow().isoformat()
                                    
                                    session.add(contributor)
                                    updated_count += 1
                                    
                                    logger.info(f"Updated {contributor.login} with email: {contributor.email}")
                        
                        # Commit after each batch
                        session.commit()
                        
                except Exception as e:
                    logger.warning(f"Error fetching batch of contributors: {e}")
                    continue
        
        # Count total contributors with emails
        email_count = session.exec(
            select(func.count()).select_from(GitHubContributor)
            .where(GitHubContributor.organization_id == organization.id)
            .where(GitHubContributor.email != None)
        ).one()
        
        return Message(
            message=f"Updated {updated_count} contributors with email addresses using bulk GraphQL API. "
                   f"Total contributors with emails: {email_count}"
        )
        
    except Exception as e:
        logger.error(f"Error fetching contributor emails: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch contributor emails: {str(e)}"
        )


@router.post("/user/orgs/sync")
async def sync_user_organizations(
    session: SessionDep,
    current_user: CurrentUser
) -> Any:
    """
    Sync the current user's GitHub organizations to the database.
    This will fetch organizations from GitHub API and store them.
    """
    
    # Verify user has GitHub OAuth connection
    statement = select(GitHubOAuth).where(GitHubOAuth.owner_id == current_user.id)
    github_oauth = session.exec(statement).first()
    
    if not github_oauth or not github_oauth.is_active:
        raise HTTPException(
            status_code=401, 
            detail="GitHub connection required. Please connect your GitHub account first."
        )
    
    # Check if user has required scope
    scopes = github_oauth.scopes.split(",") if github_oauth.scopes else []
    if "read:org" not in scopes:
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions. 'read:org' scope required to access organization data."
        )
    
    try:
        # Decrypt access token
        access_token = encryption_service.decrypt(github_oauth.encrypted_access_token)
        
        async with httpx.AsyncClient() as client:
            # Get user's organizations from GitHub
            response = await client.get(
                "https://api.github.com/user/orgs",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            orgs_data = response.json()
            
            synced_orgs = []
            now = datetime.utcnow().isoformat()
            
            for org_data in orgs_data:
                # Check if organization already exists
                existing_org = session.exec(
                    select(GitHubOrganization).where(GitHubOrganization.github_id == org_data["id"])
                ).first()
                
                if existing_org:
                    # Update existing organization
                    existing_org.name = org_data["login"]
                    existing_org.description = org_data.get("description")
                    existing_org.html_url = org_data.get("html_url", f"https://github.com/{org_data['login']}")
                    existing_org.avatar_url = org_data.get("avatar_url")
                    existing_org.public_repos = org_data.get("public_repos")
                    existing_org.followers = org_data.get("followers")
                    existing_org.following = org_data.get("following")
                    existing_org.location = org_data.get("location")
                    existing_org.email = org_data.get("email")
                    existing_org.blog = org_data.get("blog")
                    existing_org.company = org_data.get("company")
                    existing_org.twitter_username = org_data.get("twitter_username")
                    existing_org.updated_at = now
                    existing_org.last_sync_at = now
                    
                    organization = existing_org
                    action = "updated"
                else:
                    # Create new organization
                    organization = GitHubOrganization(
                        github_id=org_data["id"],
                        name=org_data["login"],
                        description=org_data.get("description"),
                        html_url=org_data.get("html_url", f"https://github.com/{org_data['login']}"),
                        avatar_url=org_data.get("avatar_url"),
                        public_repos=org_data.get("public_repos"),
                        followers=org_data.get("followers"),
                        following=org_data.get("following"),
                        location=org_data.get("location"),
                        email=org_data.get("email"),
                        blog=org_data.get("blog"),
                        company=org_data.get("company"),
                        twitter_username=org_data.get("twitter_username"),
                        created_at=now,
                        updated_at=now,
                        last_sync_at=now,
                        discovered_by_id=current_user.id
                    )
                    session.add(organization)
                    action = "added"
                
                session.commit()
                
                synced_orgs.append({
                    "id": organization.github_id,
                    "login": organization.name,
                    "action": action
                })
            
            return {
                "message": f"Successfully synced {len(synced_orgs)} organizations",
                "organizations_synced": synced_orgs,
                "total_count": len(synced_orgs)
            }
        
    except httpx.HTTPError as e:
        if hasattr(e, 'response') and e.response and e.response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail="Access denied. You may not have the 'read:org' scope or permission to view organizations."
            )
        else:
            raise HTTPException(
                status_code=400, 
                detail=f"GitHub API error: {str(e)}"
            )
    except Exception as e:
        logger.error(f"Error syncing user organizations: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync user organizations: {str(e)}"
        )