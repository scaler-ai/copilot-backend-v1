"""
Enhanced Employee-GitHub Mapping Service
Provides improved matching algorithms for mapping DarwinBox employees to GitHub contributors
"""
import re
from typing import Dict, List, Tuple, Optional
from difflib import SequenceMatcher
from datetime import datetime
import logging

from sqlmodel import Session, select
from app.models import (
    DarwinBoxEmployee,
    GitHubContributor,
    EmployeeGitHubMapping,
    User
)

logger = logging.getLogger(__name__)


class EnhancedMappingService:
    """Service for enhanced employee-GitHub account mapping with multiple matching strategies"""
    
    def __init__(self):
        # Common email domain variations to normalize
        self.email_normalizations = {
            '@gmail.com': ['@googlemail.com'],
            '@outlook.com': ['@hotmail.com', '@live.com', '@msn.com'],
        }
        
    def normalize_email(self, email: str) -> str:
        """Normalize email for better matching"""
        if not email:
            return ""
        
        email = email.lower().strip()
        
        # Remove dots from gmail addresses (they're ignored by gmail)
        if '@gmail.com' in email or '@googlemail.com' in email:
            local, domain = email.split('@')
            local = local.replace('.', '')
            email = f"{local}@{domain}"
        
        # Normalize common domain variations
        for standard, variations in self.email_normalizations.items():
            for variant in variations:
                if email.endswith(variant):
                    email = email.replace(variant, standard)
                    break
        
        return email
    
    def extract_name_parts(self, full_name: str) -> Dict[str, str]:
        """Extract first, middle, and last name parts"""
        if not full_name:
            return {"first": "", "middle": "", "last": "", "full": ""}
        
        # Clean the name
        name = re.sub(r'[^\w\s-]', '', full_name).strip()
        parts = name.split()
        
        result = {
            "full": name.lower(),
            "first": parts[0].lower() if parts else "",
            "middle": " ".join(parts[1:-1]).lower() if len(parts) > 2 else "",
            "last": parts[-1].lower() if len(parts) > 1 else "",
            "initials": "".join(p[0].lower() for p in parts if p)
        }
        
        return result
    
    def calculate_name_similarity(self, name1: str, name2: str) -> float:
        """Calculate similarity between two names"""
        if not name1 or not name2:
            return 0.0
        
        # Direct comparison
        if name1.lower() == name2.lower():
            return 1.0
        
        # Extract parts
        parts1 = self.extract_name_parts(name1)
        parts2 = self.extract_name_parts(name2)
        
        scores = []
        
        # Full name similarity
        full_sim = SequenceMatcher(None, parts1["full"], parts2["full"]).ratio()
        scores.append(full_sim * 1.0)  # Full weight
        
        # First name match (high weight)
        if parts1["first"] and parts2["first"]:
            first_sim = SequenceMatcher(None, parts1["first"], parts2["first"]).ratio()
            scores.append(first_sim * 1.5)  # Higher weight for first name
        
        # Last name match (high weight)
        if parts1["last"] and parts2["last"]:
            last_sim = SequenceMatcher(None, parts1["last"], parts2["last"]).ratio()
            scores.append(last_sim * 1.5)  # Higher weight for last name
        
        # Check if one name contains the other
        if parts1["full"] in parts2["full"] or parts2["full"] in parts1["full"]:
            scores.append(0.8)
        
        # Check initials match
        if parts1["initials"] == parts2["initials"] and len(parts1["initials"]) > 1:
            scores.append(0.7)
        
        # Return weighted average
        return sum(scores) / len(scores) if scores else 0.0
    
    def extract_email_username(self, email: str) -> str:
        """Extract username part from email"""
        if not email or '@' not in email:
            return ""
        return email.split('@')[0].lower()
    
    def calculate_email_similarity(self, email1: str, email2: str) -> float:
        """Calculate similarity between two emails"""
        if not email1 or not email2:
            return 0.0
        
        # Normalize emails
        norm_email1 = self.normalize_email(email1)
        norm_email2 = self.normalize_email(email2)
        
        # Exact match after normalization
        if norm_email1 == norm_email2:
            return 1.0
        
        # Extract usernames
        user1 = self.extract_email_username(norm_email1)
        user2 = self.extract_email_username(norm_email2)
        
        # Username similarity
        username_sim = SequenceMatcher(None, user1, user2).ratio()
        
        # Check if domains match
        domain1 = norm_email1.split('@')[1] if '@' in norm_email1 else ""
        domain2 = norm_email2.split('@')[1] if '@' in norm_email2 else ""
        domain_match = 1.0 if domain1 == domain2 else 0.0
        
        # Weighted score (username is more important than domain for personal emails)
        return (username_sim * 0.7) + (domain_match * 0.3)
    
    def calculate_match_confidence(
        self, 
        employee: DarwinBoxEmployee, 
        contributor: GitHubContributor
    ) -> Tuple[float, str]:
        """
        Calculate overall match confidence between employee and contributor
        Returns: (confidence_score, match_reason)
        """
        scores = []
        reasons = []
        
        # Email matching (highest weight)
        if employee.email and contributor.email:
            email_sim = self.calculate_email_similarity(employee.email, contributor.email)
            if email_sim > 0:
                scores.append(email_sim * 2.0)  # Double weight for email
                if email_sim == 1.0:
                    reasons.append("exact_email_match")
                elif email_sim > 0.8:
                    reasons.append("strong_email_similarity")
                elif email_sim > 0.6:
                    reasons.append("moderate_email_similarity")
        
        # Name matching
        if employee.full_name and contributor.name:
            name_sim = self.calculate_name_similarity(employee.full_name, contributor.name)
            if name_sim > 0:
                scores.append(name_sim * 1.5)  # 1.5x weight for name
                if name_sim > 0.9:
                    reasons.append("strong_name_match")
                elif name_sim > 0.7:
                    reasons.append("good_name_match")
                elif name_sim > 0.5:
                    reasons.append("partial_name_match")
        
        # Username vs email username matching
        if employee.email and contributor.login:
            email_username = self.extract_email_username(employee.email)
            username_sim = SequenceMatcher(None, email_username, contributor.login.lower()).ratio()
            if username_sim > 0.7:
                scores.append(username_sim)
                reasons.append("email_username_matches_github")
        
        # Calculate final confidence
        if not scores:
            return 0.0, "no_match"
        
        # Weighted average
        confidence = sum(scores) / len(scores)
        
        # Determine match level
        if confidence >= 0.95:
            match_level = "exact_match"
        elif confidence >= 0.85:
            match_level = "high_confidence"
        elif confidence >= 0.70:
            match_level = "medium_confidence"
        elif confidence >= 0.50:
            match_level = "low_confidence"
        else:
            match_level = "unlikely_match"
        
        reason = f"{match_level} - {', '.join(reasons)}" if reasons else match_level
        
        return confidence, reason
    
    async def enhanced_auto_map(
        self,
        session: Session,
        current_user: User,
        confidence_threshold: float = 0.85,
        limit: Optional[int] = None
    ) -> Dict:
        """
        Perform enhanced auto-mapping with multiple matching strategies
        
        Args:
            session: Database session
            current_user: User performing the mapping
            confidence_threshold: Minimum confidence to create automatic mapping (0-1)
            limit: Maximum number of employees to process (None for all)
            
        Returns:
            Mapping results with statistics
        """
        try:
            # Get unmapped employees
            query = select(DarwinBoxEmployee).where(DarwinBoxEmployee.github_mapping == None)
            if limit:
                query = query.limit(limit)
            
            employees_without_mapping = session.exec(query).all()
            
            # Get all GitHub contributors
            github_contributors = session.exec(
                select(GitHubContributor)
            ).all()
            
            # Results tracking
            auto_mapped = []
            manual_review = []
            no_matches = []
            
            for employee in employees_without_mapping:
                best_match = None
                best_confidence = 0.0
                best_reason = ""
                
                # Calculate confidence for each contributor
                matches = []
                for contributor in github_contributors:
                    confidence, reason = self.calculate_match_confidence(employee, contributor)
                    if confidence > 0.3:  # Only consider matches above 30%
                        matches.append({
                            "contributor": contributor,
                            "confidence": confidence,
                            "reason": reason
                        })
                
                # Sort by confidence
                matches.sort(key=lambda x: x["confidence"], reverse=True)
                
                if matches:
                    best = matches[0]
                    best_match = best["contributor"]
                    best_confidence = best["confidence"]
                    best_reason = best["reason"]
                    
                    if best_confidence >= confidence_threshold:
                        # Create automatic mapping
                        mapping = EmployeeGitHubMapping(
                            darwinbox_employee_id=employee.id,
                            github_username=best_match.login,
                            github_id=best_match.github_id,
                            mapping_verified=True,
                            verification_method="auto_enhanced",
                            verification_notes=f"Auto-mapped with {best_confidence:.2%} confidence: {best_reason}",
                            created_at=datetime.utcnow().isoformat(),
                            updated_at=datetime.utcnow().isoformat(),
                            mapped_by_id=current_user.id
                        )
                        session.add(mapping)
                        
                        auto_mapped.append({
                            "employee_name": employee.full_name,
                            "employee_email": employee.email,
                            "github_username": best_match.login,
                            "github_email": best_match.email,
                            "confidence": best_confidence,
                            "reason": best_reason
                        })
                    else:
                        # Add to manual review list
                        manual_review.append({
                            "employee_name": employee.full_name,
                            "employee_email": employee.email,
                            "employee_id": str(employee.id),
                            "suggestions": [
                                {
                                    "github_username": m["contributor"].login,
                                    "github_email": m["contributor"].email,
                                    "github_name": m["contributor"].name,
                                    "confidence": m["confidence"],
                                    "reason": m["reason"]
                                }
                                for m in matches[:5]  # Top 5 suggestions
                            ]
                        })
                else:
                    no_matches.append({
                        "employee_name": employee.full_name,
                        "employee_email": employee.email
                    })
            
            # Commit the automatic mappings
            session.commit()
            
            return {
                "success": True,
                "summary": {
                    "total_processed": len(employees_without_mapping),
                    "auto_mapped": len(auto_mapped),
                    "manual_review_needed": len(manual_review),
                    "no_matches_found": len(no_matches),
                    "confidence_threshold": confidence_threshold
                },
                "auto_mapped": auto_mapped[:20],  # First 20 for review
                "manual_review": manual_review[:20],  # First 20 for review
                "no_matches": no_matches[:10]  # First 10 for review
            }
            
        except Exception as e:
            logger.error(f"Error in enhanced auto-mapping: {e}")
            raise


# Create singleton instance
enhanced_mapping_service = EnhancedMappingService()