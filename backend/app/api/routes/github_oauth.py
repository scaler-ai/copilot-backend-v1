"""
GitHub OAuth Integration API Routes
"""
import secrets
import httpx
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Depends
from sqlmodel import select

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
    Message,
)

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
    Get all contributors across repositories in a GitHub organization.
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
            # First, get all repositories in the organization
            repos_url = f"https://api.github.com/orgs/{org_name}/repos"
            repos_response = await client.get(
                repos_url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"type": "all", "per_page": 100}
            )
            repos_response.raise_for_status()
            repositories = repos_response.json()
            
            # Collect all unique contributors from all repositories
            all_contributors = {}
            
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
                    
                    for contributor in contributors:
                        user_id = contributor["id"]
                        if user_id not in all_contributors:
                            all_contributors[user_id] = {
                                "id": contributor["id"],
                                "login": contributor["login"],
                                "avatar_url": contributor["avatar_url"],
                                "html_url": contributor["html_url"],
                                "type": contributor["type"],
                                "total_contributions": 0,
                                "repositories": []
                            }
                        
                        all_contributors[user_id]["total_contributions"] += contributor["contributions"]
                        all_contributors[user_id]["repositories"].append({
                            "name": repo_name,
                            "contributions": contributor["contributions"],
                            "html_url": repo["html_url"]
                        })
                        
                except httpx.HTTPError:
                    # Skip repositories where we can't access contributors (private repos, etc.)
                    continue
            
            # Convert to list and sort by total contributions
            contributors_list = list(all_contributors.values())
            contributors_list.sort(key=lambda x: x["total_contributions"], reverse=True)
            
            # Apply pagination
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_contributors = contributors_list[start_idx:end_idx]
            
            return {
                "organization": org_name,
                "total_contributors": len(contributors_list),
                "total_repositories": len(repositories),
                "page": page,
                "per_page": per_page,
                "total_pages": (len(contributors_list) + per_page - 1) // per_page,
                "contributors": paginated_contributors
            }
            
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            raise HTTPException(
                status_code=404, 
                detail=f"Organization '{org_name}' not found or not accessible"
            )
        elif e.response.status_code == 403:
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
            detail=f"Failed to fetch organization contributors: {str(e)}"
        )


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
                        
                        if existing_contributor:
                            # Update existing contributor
                            existing_contributor.login = contributor_data["login"]
                            existing_contributor.avatar_url = contributor_data.get("avatar_url")
                            existing_contributor.html_url = contributor_data["html_url"]
                            existing_contributor.type = contributor_data.get("type", "User")
                            existing_contributor.site_admin = contributor_data.get("site_admin", False)
                            existing_contributor.updated_at = now
                            existing_contributor.last_sync_at = now
                            
                            contributor = existing_contributor
                        else:
                            # Create new contributor
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
                                organization_id=organization.id
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
        if e.response.status_code == 404:
            raise HTTPException(
                status_code=404, 
                detail=f"Organization '{org_name}' not found or not accessible"
            )
        elif e.response.status_code == 403:
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