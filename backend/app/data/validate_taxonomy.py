#!/usr/bin/env python3
"""
Skills Taxonomy Validator

This script validates the skills taxonomy YAML file for syntax errors,
structure issues, and data consistency problems.

Usage:
    python validate_taxonomy.py [path_to_yaml_file]

If no path is provided, it validates the default skills-taxonomy.yaml
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, Any, List, Set

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install PyYAML")
    sys.exit(1)


class TaxonomyValidator:
    """Validates the skills taxonomy structure and content"""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.skill_ids: Set[str] = set()
        
    def validate_file(self, file_path: Path) -> bool:
        """Validate a taxonomy YAML file"""
        self.errors.clear()
        self.warnings.clear()
        self.skill_ids.clear()
        
        print(f"🔍 Validating: {file_path}")
        
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
        
        # Validate structure
        self._validate_root_structure(data)
        self._validate_skill_levels(data.get('skill_levels', {}))
        self._validate_categories(data.get('categories', {}))
        self._validate_skill_pathways(data.get('skill_pathways', {}))
        self._validate_validation_rules(data.get('validation_rules', {}))
        
        # Check for duplicate skill IDs
        self._check_duplicate_ids()
        
        return len(self.errors) == 0
    
    def _validate_root_structure(self, data: Dict[str, Any]) -> None:
        """Validate root-level structure"""
        required_keys = ['version', 'categories', 'skill_levels']
        optional_keys = ['last_updated', 'schema_version', 'skill_pathways', 'validation_rules']
        
        for key in required_keys:
            if key not in data:
                self.errors.append(f"Missing required root key: {key}")
        
        # Check for unknown keys
        allowed_keys = set(required_keys + optional_keys)
        for key in data.keys():
            if key not in allowed_keys:
                self.warnings.append(f"Unknown root key: {key}")
        
        # Validate version format
        version = data.get('version')
        if version and not isinstance(version, str):
            self.errors.append("Version must be a string")
    
    def _validate_skill_levels(self, skill_levels: Dict[str, Any]) -> None:
        """Validate skill levels structure"""
        expected_levels = ['beginner', 'intermediate', 'advanced', 'expert']
        
        for level in expected_levels:
            if level not in skill_levels:
                self.errors.append(f"Missing skill level: {level}")
                continue
            
            level_data = skill_levels[level]
            if not isinstance(level_data, dict):
                self.errors.append(f"Skill level {level} must be a dictionary")
                continue
            
            # Check required fields
            required_fields = ['name', 'description', 'value']
            for field in required_fields:
                if field not in level_data:
                    self.errors.append(f"Missing {field} in skill level {level}")
            
            # Validate value is integer
            value = level_data.get('value')
            if value is not None and not isinstance(value, int):
                self.errors.append(f"Skill level {level} value must be an integer")
    
    def _validate_categories(self, categories: Dict[str, Any]) -> None:
        """Validate categories structure"""
        if not categories:
            self.errors.append("No categories found")
            return
        
        for category_id, category_data in categories.items():
            self._validate_category(category_id, category_data)
    
    def _validate_category(self, category_id: str, category_data: Dict[str, Any]) -> None:
        """Validate a single category"""
        if not isinstance(category_data, dict):
            self.errors.append(f"Category {category_id} must be a dictionary")
            return
        
        # Check required fields
        if 'name' not in category_data:
            self.errors.append(f"Missing name for category {category_id}")
        
        # Validate subcategories
        subcategories = category_data.get('subcategories', {})
        if subcategories:
            for subcat_id, subcat_data in subcategories.items():
                self._validate_subcategory(f"{category_id}.{subcat_id}", subcat_data)
    
    def _validate_subcategory(self, context: str, subcat_data: Dict[str, Any]) -> None:
        """Validate a subcategory"""
        if not isinstance(subcat_data, dict):
            self.errors.append(f"Subcategory {context} must be a dictionary")
            return
        
        # Validate skills
        skills = subcat_data.get('skills', {})
        if skills:
            for skill_key, skill_data in skills.items():
                self._validate_skill(f"{context}.{skill_key}", skill_data)
    
    def _validate_skill(self, context: str, skill_data: Dict[str, Any]) -> None:
        """Validate a single skill"""
        if not isinstance(skill_data, dict):
            self.errors.append(f"Skill {context} must be a dictionary")
            return
        
        # Check required fields
        required_fields = ['id', 'name', 'description', 'levels']
        for field in required_fields:
            if field not in skill_data:
                self.errors.append(f"Missing {field} for skill {context}")
        
        # Validate skill ID
        skill_id = skill_data.get('id')
        if skill_id:
            if not isinstance(skill_id, str):
                self.errors.append(f"Skill ID must be a string for {context}")
            elif skill_id in self.skill_ids:
                self.errors.append(f"Duplicate skill ID: {skill_id}")
            else:
                self.skill_ids.add(skill_id)
            
            # Validate ID format
            if not skill_id.replace('_', '').replace('-', '').isalnum():
                self.warnings.append(f"Skill ID {skill_id} contains special characters")
        
        # Validate levels
        levels = skill_data.get('levels', [])
        if not isinstance(levels, list):
            self.errors.append(f"Levels must be a list for skill {context}")
        else:
            valid_levels = ['beginner', 'intermediate', 'advanced', 'expert']
            for level in levels:
                if level not in valid_levels:
                    self.errors.append(f"Invalid level '{level}' for skill {context}")
        
        # Validate optional fields
        keywords = skill_data.get('keywords', [])
        if keywords and not isinstance(keywords, list):
            self.errors.append(f"Keywords must be a list for skill {context}")
        
        prerequisites = skill_data.get('prerequisites', [])
        if prerequisites and not isinstance(prerequisites, list):
            self.errors.append(f"Prerequisites must be a list for skill {context}")
        
        learning_resources = skill_data.get('learning_resources', [])
        if learning_resources and not isinstance(learning_resources, list):
            self.errors.append(f"Learning resources must be a list for skill {context}")
    
    def _validate_skill_pathways(self, pathways: Dict[str, Any]) -> None:
        """Validate skill pathways"""
        for pathway_id, pathway_data in pathways.items():
            if not isinstance(pathway_data, dict):
                self.errors.append(f"Pathway {pathway_id} must be a dictionary")
                continue
            
            if 'name' not in pathway_data:
                self.errors.append(f"Missing name for pathway {pathway_id}")
            
            skills = pathway_data.get('skills', {})
            if skills:
                for stage, skill_list in skills.items():
                    if not isinstance(skill_list, list):
                        self.errors.append(f"Skills for pathway {pathway_id}.{stage} must be a list")
    
    def _validate_validation_rules(self, rules: Dict[str, Any]) -> None:
        """Validate validation rules section"""
        if not rules:
            return
        
        # Check required fields format
        required_fields = rules.get('required_fields', [])
        if required_fields and not isinstance(required_fields, list):
            self.errors.append("validation_rules.required_fields must be a list")
        
        # Check level progression
        level_progression = rules.get('level_progression', [])
        if level_progression and not isinstance(level_progression, list):
            self.errors.append("validation_rules.level_progression must be a list")
    
    def _check_duplicate_ids(self) -> None:
        """Check for duplicate skill IDs (already done in _validate_skill)"""
        pass  # This is handled in _validate_skill
    
    def print_results(self) -> None:
        """Print validation results"""
        if self.errors:
            print(f"\n❌ Found {len(self.errors)} errors:")
            for i, error in enumerate(self.errors, 1):
                print(f"  {i}. {error}")
        
        if self.warnings:
            print(f"\n⚠️  Found {len(self.warnings)} warnings:")
            for i, warning in enumerate(self.warnings, 1):
                print(f"  {i}. {warning}")
        
        if not self.errors and not self.warnings:
            print("\n✅ Validation passed! No errors or warnings found.")
        elif not self.errors:
            print(f"\n✅ Validation passed! Found {len(self.warnings)} warnings (non-critical).")
        else:
            print(f"\n❌ Validation failed! Please fix the errors above.")
    
    def get_stats(self) -> Dict[str, int]:
        """Get validation statistics"""
        return {
            'total_skills': len(self.skill_ids),
            'errors': len(self.errors),
            'warnings': len(self.warnings)
        }


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Validate skills taxonomy YAML file')
    parser.add_argument(
        'file',
        nargs='?',
        default='skills-taxonomy.yaml',
        help='Path to the taxonomy YAML file (default: skills-taxonomy.yaml)'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show statistics'
    )
    
    args = parser.parse_args()
    
    file_path = Path(args.file)
    validator = TaxonomyValidator()
    
    print("🔧 Skills Taxonomy Validator")
    print("=" * 40)
    
    is_valid = validator.validate_file(file_path)
    validator.print_results()
    
    if args.stats:
        stats = validator.get_stats()
        print(f"\n📊 Statistics:")
        print(f"   Total skills: {stats['total_skills']}")
        print(f"   Errors: {stats['errors']}")
        print(f"   Warnings: {stats['warnings']}")
    
    # Exit with appropriate code
    sys.exit(0 if is_valid else 1)


if __name__ == '__main__':
    main()