"""
Skill Taxonomy Service

This service handles loading, validation, and management of the skills taxonomy
from the YAML file and provides APIs for skill-related operations.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from sqlmodel import Session, select

from app.core.config import settings
from app.models import User, UserSkill, SkillGap, SkillMatchResult, SkillTaxonomyResponse

logger = logging.getLogger(__name__)


class SkillTaxonomyService:
    """Service for managing skills taxonomy and skill-related operations"""
    
    def __init__(self):
        self._taxonomy: Optional[Dict[str, Any]] = None
        self._skills_index: Optional[Dict[str, Dict[str, Any]]] = None
        self._taxonomy_path = Path(__file__).parent.parent / "data" / "skills-taxonomy.yaml"
        self.warnings: List[str] = []
    
    def load_taxonomy(self) -> Dict[str, Any]:
        """Load and cache the skills taxonomy from YAML file"""
        try:
            if self._taxonomy is None:
                logger.info(f"Loading skills taxonomy from {self._taxonomy_path}")
                
                if not self._taxonomy_path.exists():
                    logger.error(f"Skills taxonomy file not found: {self._taxonomy_path}")
                    raise FileNotFoundError(f"Skills taxonomy file not found: {self._taxonomy_path}")
                
                with open(self._taxonomy_path, 'r', encoding='utf-8') as file:
                    self._taxonomy = yaml.safe_load(file)
                
                # Validate the loaded taxonomy
                self._validate_taxonomy(self._taxonomy)
                
                # Build skills index for faster lookups
                self._build_skills_index()
                
                logger.info(f"Successfully loaded skills taxonomy v{self._taxonomy.get('version', 'unknown')}")
            
            return self._taxonomy
        
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML file: {e}")
            raise ValueError(f"Invalid YAML format in skills taxonomy: {e}")
        except Exception as e:
            logger.error(f"Error loading skills taxonomy: {e}")
            raise
    
    def reload_taxonomy(self) -> Dict[str, Any]:
        """Force reload of the skills taxonomy"""
        self._taxonomy = None
        self._skills_index = None
        return self.load_taxonomy()
    
    def _validate_taxonomy(self, taxonomy: Dict[str, Any]) -> None:
        """Validate the structure of the loaded taxonomy"""
        required_keys = ['version', 'categories', 'skill_levels']
        
        for key in required_keys:
            if key not in taxonomy:
                raise ValueError(f"Missing required key in taxonomy: {key}")
        
        # Validate skill levels - support both SFIA and traditional formats
        skill_levels = taxonomy.get('skill_levels', {})
        
        # Check if this is SFIA format (level_1, level_2, etc.) or traditional format
        is_sfia_format = any(key.startswith('level_') for key in skill_levels.keys())
        
        if is_sfia_format:
            # SFIA format validation
            expected_sfia_levels = ['level_1', 'level_2', 'level_3', 'level_4', 'level_5', 'level_6', 'level_7']
            for level in expected_sfia_levels:
                if level not in skill_levels:
                    self.warnings.append(f"Missing SFIA skill level: {level}")
        else:
            # Traditional format validation
            expected_levels = ['beginner', 'intermediate', 'advanced', 'expert']
            for level in expected_levels:
                if level not in skill_levels:
                    self.warnings.append(f"Missing traditional skill level: {level}")
        
        # Validate categories structure
        categories = taxonomy.get('categories', {})
        if not categories:
            raise ValueError("No categories found in taxonomy")
        
        # Validate each category has required structure
        for category_id, category_data in categories.items():
            if not isinstance(category_data, dict):
                raise ValueError(f"Invalid category structure for {category_id}")
            
            if 'name' not in category_data:
                raise ValueError(f"Missing name for category {category_id}")
            
            if 'subcategories' in category_data:
                self._validate_subcategories(category_id, category_data['subcategories'])
    
    def _validate_subcategories(self, category_id: str, subcategories: Dict[str, Any]) -> None:
        """Validate subcategories and their skills"""
        for subcat_id, subcat_data in subcategories.items():
            if not isinstance(subcat_data, dict):
                raise ValueError(f"Invalid subcategory structure for {category_id}.{subcat_id}")
            
            if 'skills' in subcat_data:
                self._validate_skills(f"{category_id}.{subcat_id}", subcat_data['skills'])
    
    def _validate_skills(self, context: str, skills: Dict[str, Any]) -> None:
        """Validate individual skills"""
        for skill_id, skill_data in skills.items():
            if not isinstance(skill_data, dict):
                raise ValueError(f"Invalid skill structure for {context}.{skill_id}")
            
            required_skill_fields = ['id', 'name', 'description', 'levels']
            for field in required_skill_fields:
                if field not in skill_data:
                    raise ValueError(f"Missing {field} for skill {context}.{skill_id}")
            
            # Validate skill levels
            skill_levels = skill_data.get('levels', [])
            # Support both standard levels and certification levels
            valid_levels = ['beginner', 'intermediate', 'advanced', 'expert', 
                          'associate', 'professional', 'certified', 'fundamentals',
                          'follow', 'assist', 'apply', 'enable', 'ensure', 'advise',
                          'initiate', 'influence', 'set_strategy', 'inspire'] + list(range(1, 8))
            for level in skill_levels:
                # Convert string numbers to int for SFIA levels
                if isinstance(level, str) and level.isdigit():
                    level = int(level)
                if level not in valid_levels:
                    self.warnings.append(f"Unknown skill level '{level}' for {context}.{skill_id}")
                    # Don't raise error, just warn
    
    def _build_skills_index(self) -> None:
        """Build an index of all skills for faster lookups"""
        if not self._taxonomy:
            return
        
        self._skills_index = {}
        categories = self._taxonomy.get('categories', {})
        
        for category_id, category_data in categories.items():
            subcategories = category_data.get('subcategories', {})
            
            for subcat_id, subcat_data in subcategories.items():
                skills = subcat_data.get('skills', {})
                
                for skill_key, skill_data in skills.items():
                    skill_id = skill_data.get('id')
                    if skill_id:
                        self._skills_index[skill_id] = {
                            **skill_data,
                            'category': category_id,
                            'subcategory': subcat_id,
                            'category_name': category_data.get('name', category_id),
                            'subcategory_name': subcat_data.get('name', subcat_id)
                        }
    
    def get_skill_by_id(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """Get a skill by its ID"""
        if not self._skills_index:
            self.load_taxonomy()
        return self._skills_index.get(skill_id)
    
    def search_skills(self, query: str, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Search for skills by name, keywords, or description"""
        if not self._skills_index:
            self.load_taxonomy()
        
        query_lower = query.lower()
        results = []
        
        for skill_id, skill_data in self._skills_index.items():
            # Filter by category if specified
            if category and skill_data.get('category') != category:
                continue
            
            # Check if query matches name, description, or keywords
            matches = False
            
            # Check name
            if query_lower in skill_data.get('name', '').lower():
                matches = True
            
            # Check description
            elif query_lower in skill_data.get('description', '').lower():
                matches = True
            
            # Check keywords
            elif any(query_lower in keyword.lower() for keyword in skill_data.get('keywords', [])):
                matches = True
            
            if matches:
                results.append(skill_data)
                
                if len(results) >= limit:
                    break
        
        return results
    
    def get_skills_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get all skills in a specific category"""
        if not self._skills_index:
            self.load_taxonomy()
        
        return [
            skill_data for skill_data in self._skills_index.values()
            if skill_data.get('category') == category
        ]
    
    def get_skill_pathways(self) -> Dict[str, Any]:
        """Get all skill learning pathways"""
        taxonomy = self.load_taxonomy()
        return taxonomy.get('skill_pathways', {})
    
    def get_skill_levels(self) -> Dict[str, Any]:
        """Get skill level definitions"""
        taxonomy = self.load_taxonomy()
        return taxonomy.get('skill_levels', {})
    
    def validate_skill_level(self, skill_id: str, level: str) -> bool:
        """Validate if a skill supports a specific level"""
        skill = self.get_skill_by_id(skill_id)
        if not skill:
            return False
        
        supported_levels = skill.get('levels', [])
        
        # Handle both SFIA numeric levels (1-7) and text levels (beginner, etc.)
        if isinstance(level, str):
            # Convert text levels to SFIA levels if using SFIA taxonomy
            taxonomy = self.load_taxonomy()
            if 'sfia' in taxonomy.get('framework_source', '').lower():
                level_mapping = {
                    'beginner': 1,
                    'intermediate': 2, 
                    'advanced': 3,
                    'expert': 4
                }
                level = level_mapping.get(level, level)
        
        return level in supported_levels
    
    def is_sfia_based(self) -> bool:
        """Check if the taxonomy is SFIA-based"""
        taxonomy = self.load_taxonomy()
        framework_source = taxonomy.get('framework_source', '')
        return 'sfia' in framework_source.lower()
    
    def get_sfia_skill_code(self, skill_id: str) -> Optional[str]:
        """Get the SFIA skill code for a skill"""
        skill = self.get_skill_by_id(skill_id)
        if not skill:
            return None
        return skill.get('sfia_code')
    
    def get_skills_by_sfia_code(self, sfia_code: str) -> List[Dict[str, Any]]:
        """Get all skills that map to a specific SFIA code"""
        if not self._skills_index:
            self.load_taxonomy()
        
        return [
            skill_data for skill_data in self._skills_index.values()
            if skill_data.get('sfia_code') == sfia_code
        ]
    
    def convert_to_sfia_level(self, text_level: str) -> Optional[int]:
        """Convert text skill level to SFIA numeric level"""
        level_mapping = {
            'beginner': 1,
            'intermediate': 2,
            'advanced': 3,
            'expert': 4,
            'follow': 1,
            'assist': 2,
            'apply': 3,
            'enable': 4,
            'ensure': 5,
            'advise': 5,
            'initiate': 6,
            'influence': 6,
            'set_strategy': 7,
            'inspire': 7
        }
        return level_mapping.get(text_level.lower())
    
    def get_sfia_level_name(self, level: int) -> Optional[str]:
        """Get SFIA level name from numeric level"""
        taxonomy = self.load_taxonomy()
        skill_levels = taxonomy.get('skill_levels', {})
        
        level_key = f'level_{level}'
        if level_key in skill_levels:
            return skill_levels[level_key].get('name')
        
        return None
    
    def get_skill_prerequisites(self, skill_id: str) -> List[str]:
        """Get prerequisites for a skill"""
        skill = self.get_skill_by_id(skill_id)
        if not skill:
            return []
        
        return skill.get('prerequisites', [])
    
    def analyze_skill_gaps(
        self, 
        user_skills: List[UserSkill], 
        required_skills: List[Dict[str, Any]]
    ) -> List[SkillGap]:
        """Analyze gaps between user skills and requirements"""
        gaps = []
        
        # Create a map of user skills by skill_id
        user_skill_map = {skill.skill_id: skill for skill in user_skills}
        
        # Skill level values for comparison
        level_values = {'beginner': 1, 'intermediate': 2, 'advanced': 3, 'expert': 4}
        
        for requirement in required_skills:
            skill_id = requirement.get('skill_id')
            required_level = requirement.get('required_level', 'beginner')
            required_value = level_values.get(required_level, 1)
            
            skill_info = self.get_skill_by_id(skill_id)
            skill_name = skill_info.get('name', skill_id) if skill_info else skill_id
            
            user_skill = user_skill_map.get(skill_id)
            
            if not user_skill:
                # User doesn't have this skill at all
                gap = SkillGap(
                    skill_id=skill_id,
                    skill_name=skill_name,
                    required_level=required_level,
                    current_level=None,
                    gap_severity="critical",
                    has_skill=False,
                    proficiency_score=None,
                    recommendation=f"Learn {skill_name} to {required_level} level"
                )
            else:
                # User has the skill, check if level is sufficient
                current_level = user_skill.skill_level
                current_value = level_values.get(current_level, 1)
                
                if current_value >= required_value:
                    # Skill level is sufficient
                    gap = SkillGap(
                        skill_id=skill_id,
                        skill_name=skill_name,
                        required_level=required_level,
                        current_level=current_level,
                        gap_severity="none",
                        has_skill=True,
                        proficiency_score=user_skill.proficiency_score,
                        recommendation=None
                    )
                else:
                    # Skill level is insufficient
                    level_gap = required_value - current_value
                    severity = "major" if level_gap >= 2 else "minor"
                    
                    gap = SkillGap(
                        skill_id=skill_id,
                        skill_name=skill_name,
                        required_level=required_level,
                        current_level=current_level,
                        gap_severity=severity,
                        has_skill=True,
                        proficiency_score=user_skill.proficiency_score,
                        recommendation=f"Improve {skill_name} from {current_level} to {required_level}"
                    )
            
            gaps.append(gap)
        
        return gaps
    
    def calculate_skill_match_score(
        self, 
        user_skills: List[UserSkill], 
        required_skills: List[Dict[str, Any]]
    ) -> float:
        """Calculate overall skill match percentage"""
        if not required_skills:
            return 100.0
        
        gaps = self.analyze_skill_gaps(user_skills, required_skills)
        
        # Calculate score based on gap severity
        total_score = 0
        max_possible_score = len(required_skills) * 100
        
        for gap in gaps:
            if gap.gap_severity == "none":
                score = 100
            elif gap.gap_severity == "minor":
                score = 75
            elif gap.gap_severity == "major":
                score = 40
            else:  # critical
                score = 0
            
            total_score += score
        
        return (total_score / max_possible_score) * 100 if max_possible_score > 0 else 0.0
    
    def get_taxonomy_response(self) -> SkillTaxonomyResponse:
        """Get formatted taxonomy response for API"""
        taxonomy = self.load_taxonomy()
        
        return SkillTaxonomyResponse(
            categories=taxonomy.get('categories', {}),
            skill_levels=taxonomy.get('skill_levels', {}),
            skill_pathways=taxonomy.get('skill_pathways', {}),
            version=taxonomy.get('version', '1.0'),
            last_updated=taxonomy.get('last_updated', '')
        )


# Global instance
skill_taxonomy_service = SkillTaxonomyService()


def get_skill_taxonomy_service() -> SkillTaxonomyService:
    """Dependency injection for skill taxonomy service"""
    return skill_taxonomy_service


def validate_skill_exists(skill_id: str) -> bool:
    """Utility function to validate if a skill exists in taxonomy"""
    service = get_skill_taxonomy_service()
    return service.get_skill_by_id(skill_id) is not None


def get_skill_name(skill_id: str) -> str:
    """Utility function to get skill name from ID"""
    service = get_skill_taxonomy_service()
    skill = service.get_skill_by_id(skill_id)
    return skill.get('name', skill_id) if skill else skill_id