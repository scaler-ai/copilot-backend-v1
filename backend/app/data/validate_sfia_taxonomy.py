#!/usr/bin/env python3
"""
SFIA-Based Skills Taxonomy Validator

This script validates the SFIA-based skills taxonomy YAML file for:
- SFIA framework compliance
- Proper skill code format (3-4 letter codes)
- Correct proficiency levels (1-7)
- Category alignment with SFIA 9 structure
- Custom skill mappings to official SFIA skills

Usage:
    python validate_sfia_taxonomy.py [path_to_yaml_file]

If no path is provided, it validates the default skills-taxonomy-sfia.yaml
"""

import sys
import argparse
import re
from pathlib import Path
from typing import Dict, Any, List, Set

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install PyYAML")
    sys.exit(1)


class SFIATaxonomyValidator:
    """Validates SFIA-based skills taxonomy structure and content"""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.skill_ids: Set[str] = set()
        self.sfia_skill_codes: Set[str] = set()
        self.custom_skills: Set[str] = set()
        
        # SFIA 9 standard categories
        self.sfia_categories = {
            "strategy_and_architecture",
            "change_and_transformation", 
            "development_and_implementation",
            "delivery_and_operation",
            "people_and_skills",
            "relationships_and_engagement"
        }
        
        # SFIA proficiency levels (1-7)
        self.sfia_levels = [1, 2, 3, 4, 5, 6, 7]
        
    def validate_file(self, file_path: Path) -> bool:
        """Validate a SFIA-based taxonomy YAML file"""
        self.errors.clear()
        self.warnings.clear()
        self.skill_ids.clear()
        self.sfia_skill_codes.clear()
        self.custom_skills.clear()
        
        print(f"🔍 Validating SFIA-based taxonomy: {file_path}")
        
        # Check file exists
        if not file_path.exists():
            self.errors.append(f"File not found: {file_path}")
            return False
        
        # Parse YAML
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                data = yaml.safe_load(file)
        except yaml.YAMLError as e:
            self.errors.append(f"YAML syntax error: {e}")
            return False
        except Exception as e:
            self.errors.append(f"Error reading file: {e}")
            return False
        
        if not isinstance(data, dict):
            self.errors.append("Root element must be a dictionary")
            return False
        
        # Validate SFIA-specific structure
        self._validate_sfia_root_structure(data)
        self._validate_sfia_skill_levels(data.get('skill_levels', {}))
        self._validate_sfia_categories(data.get('categories', {}))
        self._validate_skill_pathways(data.get('skill_pathways', {}))
        self._validate_sfia_validation_rules(data.get('validation_rules', {}))
        self._validate_custom_mappings(data.get('custom_skill_mappings', {}))
        
        # SFIA-specific validations
        self._check_sfia_compliance()
        self._validate_skill_code_format()
        
        return len(self.errors) == 0
    
    def _validate_sfia_root_structure(self, data: Dict[str, Any]) -> None:
        """Validate SFIA-specific root structure"""
        required_keys = ['version', 'categories', 'skill_levels', 'framework_source']
        optional_keys = [
            'last_updated', 'schema_version', 'framework_url', 'skill_pathways', 
            'validation_rules', 'certifications', 'custom_skill_mappings'
        ]
        
        for key in required_keys:
            if key not in data:
                self.errors.append(f"Missing required root key: {key}")
        
        # Check SFIA framework reference
        framework_source = data.get('framework_source', '')
        if 'SFIA' not in framework_source:
            self.warnings.append("Framework source should reference SFIA")
        
        # Validate version format for SFIA
        version = data.get('version')
        if version and not re.match(r'^\d+\.\d+$', version):
            self.warnings.append("Version should follow SFIA format (e.g., '9.0')")
        
        # Check for unknown keys
        allowed_keys = set(required_keys + optional_keys)
        for key in data.keys():
            if key not in allowed_keys:
                self.warnings.append(f"Unknown root key: {key}")
    
    def _validate_sfia_skill_levels(self, skill_levels: Dict[str, Any]) -> None:
        """Validate SFIA 7-level proficiency structure"""
        expected_levels = ['level_1', 'level_2', 'level_3', 'level_4', 'level_5', 'level_6', 'level_7']
        
        for level in expected_levels:
            if level not in skill_levels:
                self.errors.append(f"Missing SFIA skill level: {level}")
                continue
            
            level_data = skill_levels[level]
            if not isinstance(level_data, dict):
                self.errors.append(f"Skill level {level} must be a dictionary")
                continue
            
            # Check required fields for SFIA levels
            required_fields = ['name', 'description', 'value', 'sfia_level', 'responsibility']
            for field in required_fields:
                if field not in level_data:
                    self.errors.append(f"Missing {field} in skill level {level}")
            
            # Validate SFIA level value
            sfia_level = level_data.get('sfia_level')
            expected_value = int(level.split('_')[1])
            
            if sfia_level != expected_value:
                self.errors.append(f"SFIA level {level} should have sfia_level={expected_value}, got {sfia_level}")
            
            # Validate value matches SFIA level
            value = level_data.get('value')
            if value != expected_value:
                self.errors.append(f"Skill level {level} value should be {expected_value}, got {value}")
    
    def _validate_sfia_categories(self, categories: Dict[str, Any]) -> None:
        """Validate SFIA 9 categories structure"""
        if not categories:
            self.errors.append("No categories found")
            return
        
        # Check if all SFIA categories are present
        found_categories = set(categories.keys())
        missing_categories = self.sfia_categories - found_categories
        extra_categories = found_categories - self.sfia_categories
        
        if missing_categories:
            self.warnings.append(f"Missing SFIA categories: {missing_categories}")
        
        if extra_categories:
            self.warnings.append(f"Non-standard categories found: {extra_categories}")
        
        for category_id, category_data in categories.items():
            self._validate_sfia_category(category_id, category_data)
    
    def _validate_sfia_category(self, category_id: str, category_data: Dict[str, Any]) -> None:
        """Validate a single SFIA category"""
        if not isinstance(category_data, dict):
            self.errors.append(f"Category {category_id} must be a dictionary")
            return
        
        # Check required fields
        required_fields = ['name', 'description', 'sfia_category']
        for field in required_fields:
            if field not in category_data:
                self.errors.append(f"Missing {field} for category {category_id}")
        
        # Validate SFIA category alignment
        sfia_category = category_data.get('sfia_category', '')
        if category_id in self.sfia_categories and sfia_category.lower().replace(' ', '_').replace('&', 'and') != category_id:
            self.warnings.append(f"Category {category_id} SFIA category name mismatch: {sfia_category}")
        
        # Validate subcategories
        subcategories = category_data.get('subcategories', {})
        if subcategories:
            for subcat_id, subcat_data in subcategories.items():
                self._validate_sfia_subcategory(f"{category_id}.{subcat_id}", subcat_data)
    
    def _validate_sfia_subcategory(self, context: str, subcat_data: Dict[str, Any]) -> None:
        """Validate a subcategory"""
        if not isinstance(subcat_data, dict):
            self.errors.append(f"Subcategory {context} must be a dictionary")
            return
        
        # Validate skills
        skills = subcat_data.get('skills', {})
        if skills:
            for skill_key, skill_data in skills.items():
                self._validate_sfia_skill(f"{context}.{skill_key}", skill_data)
    
    def _validate_sfia_skill(self, context: str, skill_data: Dict[str, Any]) -> None:
        """Validate a single SFIA skill"""
        if not isinstance(skill_data, dict):
            self.errors.append(f"Skill {context} must be a dictionary")
            return
        
        # Check required fields for SFIA skills
        required_fields = ['id', 'name', 'description', 'levels', 'sfia_code', 'category', 'subcategory']
        for field in required_fields:
            if field not in skill_data:
                self.errors.append(f"Missing {field} for skill {context}")
        
        # Validate skill ID format (SFIA uses 3-4 letter codes)
        skill_id = skill_data.get('id')
        if skill_id:
            if not re.match(r'^[A-Z]{3,4}$', skill_id):
                self.warnings.append(f"Skill ID {skill_id} should follow SFIA format (3-4 uppercase letters)")
            
            if skill_id in self.skill_ids:
                self.errors.append(f"Duplicate skill ID: {skill_id}")
            else:
                self.skill_ids.add(skill_id)
        
        # Validate SFIA code
        sfia_code = skill_data.get('sfia_code')
        if sfia_code:
            if not re.match(r'^[A-Z]{3,4}$', sfia_code):
                self.errors.append(f"SFIA code {sfia_code} should be 3-4 uppercase letters")
            
            self.sfia_skill_codes.add(sfia_code)
            
            # Check if this is a custom skill (ID != SFIA code)
            if skill_id != sfia_code:
                self.custom_skills.add(skill_id)
                
                # Custom skills should have parent_skill
                if 'parent_skill' not in skill_data:
                    self.warnings.append(f"Custom skill {skill_id} should specify parent_skill")
        
        # Validate levels (should be list of integers 1-7)
        levels = skill_data.get('levels', [])
        if not isinstance(levels, list):
            self.errors.append(f"Levels must be a list for skill {context}")
        else:
            for level in levels:
                if not isinstance(level, int) or level not in self.sfia_levels:
                    self.errors.append(f"Invalid SFIA level {level} for skill {context}. Must be 1-7")
        
        # Validate category alignment
        category = skill_data.get('category')
        if category and category not in self.sfia_categories:
            self.warnings.append(f"Skill {skill_id} references non-SFIA category: {category}")
        
        # Validate optional fields
        keywords = skill_data.get('keywords', [])
        if keywords and not isinstance(keywords, list):
            self.errors.append(f"Keywords must be a list for skill {context}")
        
        parent_skill = skill_data.get('parent_skill')
        if parent_skill and not re.match(r'^[A-Z]{3,4}$', parent_skill):
            self.errors.append(f"Parent skill {parent_skill} should be a valid SFIA code")
    
    def _validate_skill_pathways(self, pathways: Dict[str, Any]) -> None:
        """Validate SFIA-based skill pathways"""
        for pathway_id, pathway_data in pathways.items():
            if not isinstance(pathway_data, dict):
                self.errors.append(f"Pathway {pathway_id} must be a dictionary")
                continue
            
            if 'name' not in pathway_data:
                self.errors.append(f"Missing name for pathway {pathway_id}")
            
            # Check if pathway is marked as SFIA-aligned
            sfia_aligned = pathway_data.get('sfia_aligned', False)
            if sfia_aligned:
                skills = pathway_data.get('skills', {})
                if skills:
                    for stage, skill_list in skills.items():
                        if not isinstance(skill_list, list):
                            self.errors.append(f"Skills for pathway {pathway_id}.{stage} must be a list")
                        else:
                            # Validate skill codes in pathway
                            for skill_code in skill_list:
                                if not re.match(r'^[A-Z]{3,4}$', skill_code):
                                    self.warnings.append(f"Pathway {pathway_id} contains invalid skill code: {skill_code}")
    
    def _validate_sfia_validation_rules(self, rules: Dict[str, Any]) -> None:
        """Validate SFIA-specific validation rules"""
        if not rules:
            self.warnings.append("No validation rules defined")
            return
        
        # Check SFIA compliance settings
        sfia_compliance = rules.get('sfia_compliance', {})
        if sfia_compliance:
            enforce_codes = sfia_compliance.get('enforce_sfia_codes', False)
            allow_custom = sfia_compliance.get('allow_custom_extensions', False)
            
            if enforce_codes and not allow_custom:
                # In strict mode, check for non-SFIA skills
                for skill_id in self.custom_skills:
                    self.warnings.append(f"Custom skill {skill_id} found in strict SFIA mode")
        
        # Check category validation
        category_validation = rules.get('category_validation', {})
        if category_validation:
            allowed_categories = set(category_validation.get('allowed_categories', []))
            if allowed_categories and allowed_categories != self.sfia_categories:
                missing = self.sfia_categories - allowed_categories
                extra = allowed_categories - self.sfia_categories
                if missing:
                    self.warnings.append(f"Validation rules missing SFIA categories: {missing}")
                if extra:
                    self.warnings.append(f"Validation rules include non-SFIA categories: {extra}")
    
    def _validate_custom_mappings(self, mappings: Dict[str, str]) -> None:
        """Validate custom skill mappings to SFIA skills"""
        for custom_skill, sfia_skill in mappings.items():
            if not re.match(r'^[A-Z]{3,4}$', custom_skill):
                self.errors.append(f"Custom skill mapping key {custom_skill} should be valid skill code")
            
            if not re.match(r'^[A-Z]{3,4}$', sfia_skill):
                self.errors.append(f"SFIA skill mapping value {sfia_skill} should be valid SFIA code")
            
            # Check if the custom skill actually exists in taxonomy
            if custom_skill not in self.skill_ids:
                self.warnings.append(f"Custom skill mapping references non-existent skill: {custom_skill}")
    
    def _check_sfia_compliance(self) -> None:
        """Check overall SFIA compliance"""
        total_skills = len(self.skill_ids)
        custom_skills_count = len(self.custom_skills)
        sfia_skills_count = total_skills - custom_skills_count
        
        if custom_skills_count > sfia_skills_count:
            self.warnings.append(f"More custom skills ({custom_skills_count}) than SFIA skills ({sfia_skills_count})")
        
        # Check for common SFIA skills that might be missing
        common_sfia_skills = {'PROG', 'TEST', 'ARCH', 'PRMG', 'BUAN', 'SYAD', 'ITSM'}
        missing_common = common_sfia_skills - self.sfia_skill_codes
        if missing_common:
            self.warnings.append(f"Missing common SFIA skills: {missing_common}")
    
    def _validate_skill_code_format(self) -> None:
        """Validate all skill codes follow SFIA format"""
        invalid_codes = []
        for skill_id in self.skill_ids:
            if not re.match(r'^[A-Z]{3,4}$', skill_id):
                invalid_codes.append(skill_id)
        
        if invalid_codes:
            self.warnings.append(f"Skills with non-SFIA code format: {invalid_codes}")
    
    def print_results(self) -> None:
        """Print validation results with SFIA-specific information"""
        if self.errors:
            print(f"\n❌ Found {len(self.errors)} errors:")
            for i, error in enumerate(self.errors, 1):
                print(f"  {i}. {error}")
        
        if self.warnings:
            print(f"\n⚠️  Found {len(self.warnings)} warnings:")
            for i, warning in enumerate(self.warnings, 1):
                print(f"  {i}. {warning}")
        
        if not self.errors and not self.warnings:
            print("\n✅ SFIA validation passed! No errors or warnings found.")
        elif not self.errors:
            print(f"\n✅ SFIA validation passed! Found {len(self.warnings)} warnings (non-critical).")
        else:
            print(f"\n❌ SFIA validation failed! Please fix the errors above.")
    
    def get_sfia_stats(self) -> Dict[str, int]:
        """Get SFIA-specific validation statistics"""
        return {
            'total_skills': len(self.skill_ids),
            'sfia_skills': len(self.sfia_skill_codes),
            'custom_skills': len(self.custom_skills),
            'sfia_categories': len(self.sfia_categories),
            'errors': len(self.errors),
            'warnings': len(self.warnings)
        }


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Validate SFIA-based skills taxonomy YAML file')
    parser.add_argument(
        'file',
        nargs='?',
        default='skills-taxonomy-sfia.yaml',
        help='Path to the SFIA taxonomy YAML file (default: skills-taxonomy-sfia.yaml)'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show SFIA compliance statistics'
    )
    parser.add_argument(
        '--strict',
        action='store_true',
        help='Enable strict SFIA compliance checking'
    )
    
    args = parser.parse_args()
    
    file_path = Path(args.file)
    validator = SFIATaxonomyValidator()
    
    print("🔧 SFIA-Based Skills Taxonomy Validator")
    print("=" * 50)
    
    is_valid = validator.validate_file(file_path)
    validator.print_results()
    
    if args.stats:
        stats = validator.get_sfia_stats()
        print(f"\n📊 SFIA Compliance Statistics:")
        print(f"   Total skills: {stats['total_skills']}")
        print(f"   Official SFIA skills: {stats['sfia_skills']}")
        print(f"   Custom extensions: {stats['custom_skills']}")
        print(f"   SFIA categories: {stats['sfia_categories']}/6")
        print(f"   Errors: {stats['errors']}")
        print(f"   Warnings: {stats['warnings']}")
        
        # Calculate compliance percentage
        if stats['total_skills'] > 0:
            compliance = (stats['sfia_skills'] / stats['total_skills']) * 100
            print(f"   SFIA Compliance: {compliance:.1f}%")
    
    # Exit with appropriate code
    sys.exit(0 if is_valid else 1)


if __name__ == '__main__':
    main()