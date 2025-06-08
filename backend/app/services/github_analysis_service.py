"""
GitHub Analysis Service

This service handles detailed GitHub activity collection and analysis for skill assessment.
It fetches comprehensive data about pull requests, code reviews, issues, and other 
contributions to build detailed skill profiles.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlmodel import Session, select

from app.core.encryption import encryption_service
from app.models import (
    GitHubOAuth,
    GitHubContributor, 
    GitHubActivity,
    GitHubPullRequest,
    GitHubCodeReview,
    GitHubIssueActivity,
    ContributorAnalysis,
    GitHubSkillRating,
    User
)
from app.services.llm_service import llm_service
from app.services.skill_service import skill_taxonomy_service

logger = logging.getLogger(__name__)


class GitHubActivityData:
    """Data structure for organizing GitHub activity analysis"""
    
    def __init__(self):
        self.pull_requests: List[Dict[str, Any]] = []
        self.code_reviews: List[Dict[str, Any]] = []
        self.issues: List[Dict[str, Any]] = []
        self.commits: List[Dict[str, Any]] = []
        self.repositories: set = set()
        self.languages: Dict[str, int] = {}
        self.total_activities: int = 0


class GitHubAnalysisService:
    """Service for analyzing GitHub activities and inferring skills"""
    
    def __init__(self):
        self.github_api_base = "https://api.github.com"
    
    async def collect_contributor_activities(
        self,
        contributor: GitHubContributor,
        github_oauth: GitHubOAuth,
        session: Session,
        months_back: int = 12
    ) -> GitHubActivityData:
        """Collect comprehensive GitHub activities for a contributor"""
        
        try:
            # Decrypt access token
            access_token = encryption_service.decrypt(github_oauth.encrypted_access_token)
            
            # Calculate date range
            since_date = datetime.utcnow() - timedelta(days=months_back * 30)
            since_iso = since_date.isoformat()
            
            activity_data = GitHubActivityData()
            
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Collect pull requests
                await self._collect_pull_requests(
                    client, headers, contributor.login, since_iso, activity_data, session
                )
                
                # Collect code reviews
                await self._collect_code_reviews(
                    client, headers, contributor.login, since_iso, activity_data, session
                )
                
                # Collect issue activities
                await self._collect_issue_activities(
                    client, headers, contributor.login, since_iso, activity_data, session
                )
                
                # Collect commit activities
                await self._collect_commit_activities(
                    client, headers, contributor.login, since_iso, activity_data, session
                )
            
            logger.info(f"Collected {activity_data.total_activities} activities for {contributor.login}")
            return activity_data
            
        except Exception as e:
            logger.error(f"Error collecting activities for {contributor.login}: {e}")
            raise
    
    async def _collect_pull_requests(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        username: str,
        since_date: str,
        activity_data: GitHubActivityData,
        session: Session
    ) -> None:
        """Collect pull request data"""
        
        # Search for PRs authored by the user
        search_query = f"author:{username} type:pr created:>={since_date[:10]}"
        
        try:
            response = await client.get(
                f"{self.github_api_base}/search/issues",
                headers=headers,
                params={
                    "q": search_query,
                    "sort": "created",
                    "order": "desc",
                    "per_page": 100
                }
            )
            response.raise_for_status()
            search_results = response.json()
            
            for pr_item in search_results.get("items", []):
                try:
                    # Get detailed PR information
                    pr_url = pr_item["pull_request"]["url"]
                    pr_response = await client.get(pr_url, headers=headers)
                    pr_response.raise_for_status()
                    pr_data = pr_response.json()
                    
                    # Extract language information from repository
                    repo_full_name = pr_item["repository_url"].split("/")[-2:]
                    repo_owner, repo_name = repo_full_name[0], repo_full_name[1]
                    
                    # Get repository languages
                    repo_languages = await self._get_repository_languages(
                        client, headers, repo_owner, repo_name
                    )
                    
                    activity_data.pull_requests.append({
                        "github_pr_id": pr_data["id"],
                        "number": pr_data["number"],
                        "title": pr_data["title"],
                        "description": pr_data.get("body", ""),
                        "state": pr_data["state"],
                        "additions": pr_data.get("additions", 0),
                        "deletions": pr_data.get("deletions", 0),
                        "changed_files": pr_data.get("changed_files", 0),
                        "commits": pr_data.get("commits", 0),
                        "repository_name": f"{repo_owner}/{repo_name}",
                        "repository_url": pr_item["repository_url"],
                        "languages": repo_languages,
                        "created_at": pr_data["created_at"],
                        "merged_at": pr_data.get("merged_at"),
                        "closed_at": pr_data.get("closed_at"),
                        "is_draft": pr_data.get("draft", False)
                    })
                    
                    activity_data.repositories.add(f"{repo_owner}/{repo_name}")
                    activity_data.total_activities += 1
                    
                    # Update language statistics
                    for lang, bytes_count in repo_languages.items():
                        activity_data.languages[lang] = activity_data.languages.get(lang, 0) + bytes_count
                    
                except Exception as e:
                    logger.warning(f"Error processing PR {pr_item.get('number', 'unknown')}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error collecting pull requests: {e}")
    
    async def _collect_code_reviews(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        username: str,
        since_date: str,
        activity_data: GitHubActivityData,
        session: Session
    ) -> None:
        """Collect code review data"""
        
        # Search for PRs reviewed by the user
        search_query = f"reviewed-by:{username} type:pr created:>={since_date[:10]}"
        
        try:
            response = await client.get(
                f"{self.github_api_base}/search/issues",
                headers=headers,
                params={
                    "q": search_query,
                    "sort": "created",
                    "order": "desc",
                    "per_page": 100
                }
            )
            response.raise_for_status()
            search_results = response.json()
            
            for pr_item in search_results.get("items", []):
                try:
                    # Get PR reviews
                    pr_url = pr_item["pull_request"]["url"]
                    reviews_url = f"{pr_url}/reviews"
                    
                    reviews_response = await client.get(reviews_url, headers=headers)
                    reviews_response.raise_for_status()
                    reviews_data = reviews_response.json()
                    
                    # Filter reviews by the user
                    user_reviews = [
                        review for review in reviews_data 
                        if review["user"]["login"] == username
                    ]
                    
                    for review in user_reviews:
                        activity_data.code_reviews.append({
                            "github_review_id": review["id"],
                            "pr_number": pr_item["number"],
                            "pr_title": pr_item["title"],
                            "repository_name": pr_item["repository_url"].split("/")[-2:],
                            "review_state": review["state"],
                            "submitted_at": review["submitted_at"],
                            "body": review.get("body", "")
                        })
                        
                        activity_data.total_activities += 1
                    
                except Exception as e:
                    logger.warning(f"Error processing reviews for PR {pr_item.get('number', 'unknown')}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error collecting code reviews: {e}")
    
    async def _collect_issue_activities(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        username: str,
        since_date: str,
        activity_data: GitHubActivityData,
        session: Session
    ) -> None:
        """Collect issue-related activities"""
        
        # Search for issues authored by the user
        search_query = f"author:{username} type:issue created:>={since_date[:10]}"
        
        try:
            response = await client.get(
                f"{self.github_api_base}/search/issues",
                headers=headers,
                params={
                    "q": search_query,
                    "sort": "created",
                    "order": "desc",
                    "per_page": 100
                }
            )
            response.raise_for_status()
            search_results = response.json()
            
            for issue_item in search_results.get("items", []):
                try:
                    repo_full_name = issue_item["repository_url"].split("/")[-2:]
                    repo_owner, repo_name = repo_full_name[0], repo_full_name[1]
                    
                    activity_data.issues.append({
                        "github_issue_id": issue_item["id"],
                        "number": issue_item["number"],
                        "title": issue_item["title"],
                        "body": issue_item.get("body", ""),
                        "state": issue_item["state"],
                        "labels": [label["name"] for label in issue_item.get("labels", [])],
                        "repository_name": f"{repo_owner}/{repo_name}",
                        "repository_url": issue_item["repository_url"],
                        "created_at": issue_item["created_at"],
                        "closed_at": issue_item.get("closed_at"),
                        "activity_type": "created"
                    })
                    
                    activity_data.repositories.add(f"{repo_owner}/{repo_name}")
                    activity_data.total_activities += 1
                    
                except Exception as e:
                    logger.warning(f"Error processing issue {issue_item.get('number', 'unknown')}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error collecting issues: {e}")
    
    async def _collect_commit_activities(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        username: str,
        since_date: str,
        activity_data: GitHubActivityData,
        session: Session
    ) -> None:
        """Collect commit activities"""
        
        # Search for commits by the user
        search_query = f"author:{username} committer-date:>={since_date[:10]}"
        
        try:
            response = await client.get(
                f"{self.github_api_base}/search/commits",
                headers={**headers, "Accept": "application/vnd.github.cloak-preview"},
                params={
                    "q": search_query,
                    "sort": "committer-date",
                    "order": "desc",
                    "per_page": 100
                }
            )
            response.raise_for_status()
            search_results = response.json()
            
            for commit_item in search_results.get("items", []):
                try:
                    repo_full_name = commit_item["repository"]["full_name"]
                    
                    activity_data.commits.append({
                        "sha": commit_item["sha"],
                        "message": commit_item["commit"]["message"],
                        "repository_name": repo_full_name,
                        "committed_date": commit_item["commit"]["committer"]["date"],
                        "additions": commit_item["stats"].get("additions", 0),
                        "deletions": commit_item["stats"].get("deletions", 0),
                        "total_changes": commit_item["stats"].get("total", 0)
                    })
                    
                    activity_data.repositories.add(repo_full_name)
                    activity_data.total_activities += 1
                    
                except Exception as e:
                    logger.warning(f"Error processing commit {commit_item.get('sha', 'unknown')}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error collecting commits: {e}")
    
    async def _get_repository_languages(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        owner: str,
        repo: str
    ) -> Dict[str, int]:
        """Get programming languages used in a repository"""
        
        try:
            response = await client.get(
                f"{self.github_api_base}/repos/{owner}/{repo}/languages",
                headers=headers
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Error getting languages for {owner}/{repo}: {e}")
            return {}
    
    async def analyze_contributor_activities(
        self,
        contributor: GitHubContributor,
        activity_data: GitHubActivityData,
        user: User,
        session: Session
    ) -> ContributorAnalysis:
        """Analyze collected activities and generate skill assessment"""
        
        try:
            # Generate technical summary using LLM
            technical_summary = await self._generate_technical_summary(
                activity_data, user, session
            )
            
            # Infer skills from activities
            skill_inferences = await self._infer_skills_from_activities(
                activity_data, technical_summary, user, session
            )
            
            # Assess career level
            career_assessment = await self._assess_career_level(
                activity_data, technical_summary, user, session
            )
            
            # Create analysis record
            analysis = ContributorAnalysis(
                contributor_id=contributor.id,
                technical_summary=technical_summary,
                skill_inferences=json.dumps(skill_inferences),
                career_level_assessment=career_assessment,
                confidence_score=self._calculate_confidence_score(activity_data),
                analysis_period_months=12,
                total_activities_analyzed=activity_data.total_activities,
                generated_by_id=user.id
            )
            
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
            
            logger.info(f"Generated analysis for contributor {contributor.login}")
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing activities for {contributor.login}: {e}")
            raise
    
    async def _generate_technical_summary(
        self,
        activity_data: GitHubActivityData,
        user: User,
        session: Session
    ) -> str:
        """Generate comprehensive technical summary using LLM"""
        
        # Prepare activity statistics
        top_languages = sorted(
            activity_data.languages.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:5]
        
        pr_stats = {
            "total": len(activity_data.pull_requests),
            "merged": len([pr for pr in activity_data.pull_requests if pr.get("merged_at")]),
            "avg_additions": sum(pr.get("additions", 0) for pr in activity_data.pull_requests) // max(len(activity_data.pull_requests), 1),
            "avg_deletions": sum(pr.get("deletions", 0) for pr in activity_data.pull_requests) // max(len(activity_data.pull_requests), 1),
            "avg_files_changed": sum(pr.get("changed_files", 0) for pr in activity_data.pull_requests) // max(len(activity_data.pull_requests), 1)
        }
        
        review_stats = {
            "total": len(activity_data.code_reviews),
            "types": {}
        }
        
        for review in activity_data.code_reviews:
            review_type = review.get("review_state", "comment")
            review_stats["types"][review_type] = review_stats["types"].get(review_type, 0) + 1
        
        prompt = f"""
        Analyze this developer's GitHub activity over the past 12 months and create a professional 
        technical summary focusing on their skills, impact, and career progression indicators.

        Activity Overview:
        - Total activities: {activity_data.total_activities}
        - Repositories contributed to: {len(activity_data.repositories)}
        - Pull requests: {pr_stats['total']} total, {pr_stats['merged']} merged
        - Code reviews: {review_stats['total']} total
        - Issues: {len(activity_data.issues)} created
        - Commits: {len(activity_data.commits)} made

        Pull Request Analysis:
        - Average lines added: {pr_stats['avg_additions']}
        - Average lines deleted: {pr_stats['avg_deletions']}
        - Average files changed: {pr_stats['avg_files_changed']}

        Code Review Analysis:
        - Review types: {json.dumps(review_stats['types'])}

        Programming Languages (by usage):
        {chr(10).join([f"- {lang}: {bytes_count} bytes" for lang, bytes_count in top_languages])}

        Repository Diversity:
        - {len(activity_data.repositories)} different repositories
        - Cross-project collaboration: {'High' if len(activity_data.repositories) > 5 else 'Medium' if len(activity_data.repositories) > 2 else 'Low'}

        Please provide:
        1. Technical depth assessment (languages, frameworks, complexity)
        2. Collaboration and leadership indicators
        3. Code quality and engineering practices
        4. Problem-solving and innovation examples
        5. Career level indicators (junior, mid-level, senior, staff+)
        6. Areas of specialization or expertise
        7. Growth trajectory and potential

        Be specific and cite quantifiable evidence from the activity data.
        """
        
        try:
            result = await llm_service.generate_response(
                user, session,
                [{"role": "user", "content": prompt}]
            )
            
            if result.get("success"):
                return result["content"]
            else:
                logger.warning(f"LLM summary generation failed: {result.get('error')}")
                return self._generate_fallback_summary(activity_data)
                
        except Exception as e:
            logger.error(f"Error generating technical summary: {e}")
            return self._generate_fallback_summary(activity_data)
    
    def _generate_fallback_summary(self, activity_data: GitHubActivityData) -> str:
        """Generate a basic summary when LLM is unavailable"""
        
        top_languages = sorted(
            activity_data.languages.items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:3]
        
        return f"""
        Technical Summary (Generated automatically):
        
        This developer has been active across {len(activity_data.repositories)} repositories, 
        contributing {activity_data.total_activities} activities over the past 12 months.
        
        Key contributions:
        - {len(activity_data.pull_requests)} pull requests submitted
        - {len(activity_data.code_reviews)} code reviews performed
        - {len(activity_data.issues)} issues created
        - {len(activity_data.commits)} commits made
        
        Primary programming languages: {', '.join([lang for lang, _ in top_languages])}
        
        Activity level: {'High' if activity_data.total_activities > 50 else 'Medium' if activity_data.total_activities > 20 else 'Low'}
        Repository diversity: {'High' if len(activity_data.repositories) > 5 else 'Medium' if len(activity_data.repositories) > 2 else 'Low'}
        """
    
    def _calculate_confidence_score(self, activity_data: GitHubActivityData) -> int:
        """Calculate confidence score for the analysis"""
        
        score = 50  # Base score
        
        # Activity volume indicators
        if activity_data.total_activities > 100:
            score += 20
        elif activity_data.total_activities > 50:
            score += 15
        elif activity_data.total_activities > 20:
            score += 10
        
        # Diversity indicators
        if len(activity_data.repositories) > 10:
            score += 15
        elif len(activity_data.repositories) > 5:
            score += 10
        elif len(activity_data.repositories) > 2:
            score += 5
        
        # Activity type diversity
        activity_types = sum([
            1 if activity_data.pull_requests else 0,
            1 if activity_data.code_reviews else 0,
            1 if activity_data.issues else 0,
            1 if activity_data.commits else 0
        ])
        score += activity_types * 5
        
        return min(100, max(10, score))
    
    async def _infer_skills_from_activities(
        self,
        activity_data: GitHubActivityData,
        technical_summary: str,
        user: User,
        session: Session
    ) -> List[Dict[str, Any]]:
        """Infer specific skills from GitHub activities"""
        
        # This will be implemented in the next iteration
        # For now, return a basic structure
        return []
    
    async def _assess_career_level(
        self,
        activity_data: GitHubActivityData,
        technical_summary: str,
        user: User,
        session: Session
    ) -> str:
        """Assess career level based on activities"""
        
        # This will be implemented in the next iteration
        # For now, return a basic assessment
        if activity_data.total_activities > 100 and len(activity_data.repositories) > 10:
            return "Senior level contributor with significant cross-project impact"
        elif activity_data.total_activities > 50 and len(activity_data.repositories) > 5:
            return "Mid-level contributor with good project diversity"
        else:
            return "Junior to mid-level contributor building experience"


# Global service instance
github_analysis_service = GitHubAnalysisService()