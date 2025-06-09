#!/usr/bin/env python3
"""
Script to run enhanced employee-GitHub mapping
This demonstrates how to use the enhanced mapping API endpoints
"""
import asyncio
import json
import httpx
from typing import Dict, Any

# Configuration
API_BASE_URL = "http://localhost:8000/api/v1"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "changethis"


async def get_auth_token() -> str:
    """Get authentication token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE_URL}/login/access-token",
            data={
                "username": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD
            }
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def get_stats(token: str) -> Dict[str, Any]:
    """Get current DarwinBox stats"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/darwinbox/stats",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return response.json()


async def run_enhanced_mapping(token: str, confidence_threshold: float = 0.85) -> Dict[str, Any]:
    """Run enhanced auto-mapping"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE_URL}/darwinbox/enhanced-auto-map",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "confidence_threshold": confidence_threshold,
                "limit": 100  # Process first 100 unmapped employees
            }
        )
        response.raise_for_status()
        return response.json()


async def review_mappings(token: str, review_items: list) -> Dict[str, Any]:
    """Review and approve/reject mappings"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{API_BASE_URL}/darwinbox/batch-review-mappings",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "mappings": review_items,
                "auto_verify": True
            }
        )
        response.raise_for_status()
        return response.json()


async def main():
    """Main execution flow"""
    print("🚀 Starting Enhanced Employee-GitHub Mapping")
    print("=" * 50)
    
    try:
        # Get authentication token
        print("🔐 Authenticating...")
        token = await get_auth_token()
        print("✅ Authentication successful")
        
        # Get initial stats
        print("\n📊 Current Statistics:")
        stats = await get_stats(token)
        print(f"  Total employees: {stats.get('total_employees', 0)}")
        print(f"  Employees with GitHub mapping: {stats.get('employees_with_github_mapping', 0)}")
        print(f"  Mapping percentage: {stats.get('github_mapping_percentage', 0):.1f}%")
        
        # Run enhanced mapping
        print("\n🤖 Running Enhanced Auto-Mapping...")
        print("  Confidence threshold: 85%")
        mapping_result = await run_enhanced_mapping(token, confidence_threshold=0.85)
        
        summary = mapping_result.get("summary", {})
        print(f"\n📋 Mapping Results:")
        print(f"  Total processed: {summary.get('total_processed', 0)}")
        print(f"  Auto-mapped: {summary.get('auto_mapped', 0)}")
        print(f"  Manual review needed: {summary.get('manual_review_needed', 0)}")
        print(f"  No matches found: {summary.get('no_matches_found', 0)}")
        
        # Show auto-mapped examples
        auto_mapped = mapping_result.get("auto_mapped", [])
        if auto_mapped:
            print(f"\n✅ Auto-Mapped Examples (showing first 5):")
            for i, mapping in enumerate(auto_mapped[:5], 1):
                print(f"  {i}. {mapping['employee_name']} → {mapping['github_username']}")
                print(f"     Confidence: {mapping['confidence']:.2%} - {mapping['reason']}")
        
        # Show manual review suggestions
        manual_review = mapping_result.get("manual_review", [])
        if manual_review:
            print(f"\n🔍 Manual Review Suggestions (showing first 5):")
            for i, review in enumerate(manual_review[:5], 1):
                print(f"  {i}. {review['employee_name']} ({review['employee_email']})")
                for j, suggestion in enumerate(review['suggestions'][:2], 1):
                    print(f"     Suggestion {j}: {suggestion['github_username']}")
                    print(f"     Confidence: {suggestion['confidence']:.2%} - {suggestion['reason']}")
            
            # Example of batch review (approve first 3 suggestions)
            review_items = []
            for review in manual_review[:3]:
                if review['suggestions']:
                    best_suggestion = review['suggestions'][0]
                    review_items.append({
                        "darwinbox_employee_id": review['employee_id'],
                        "github_username": best_suggestion['github_username'],
                        "action": "approve" if best_suggestion['confidence'] > 0.7 else "skip",
                        "notes": f"Reviewed with {best_suggestion['confidence']:.2%} confidence"
                    })
            
            if review_items:
                print(f"\n📝 Batch Reviewing {len(review_items)} mappings...")
                review_result = await review_mappings(token, review_items)
                print(f"  Approved: {review_result.get('approved', 0)}")
                print(f"  Rejected: {review_result.get('rejected', 0)}")
                print(f"  Skipped: {review_result.get('skipped', 0)}")
                if review_result.get('errors'):
                    print(f"  Errors: {len(review_result['errors'])}")
        
        # Get final stats
        print("\n📊 Final Statistics:")
        final_stats = await get_stats(token)
        print(f"  Total employees: {final_stats.get('total_employees', 0)}")
        print(f"  Employees with GitHub mapping: {final_stats.get('employees_with_github_mapping', 0)}")
        print(f"  Mapping percentage: {final_stats.get('github_mapping_percentage', 0):.1f}%")
        print(f"  Improvement: +{final_stats.get('github_mapping_percentage', 0) - stats.get('github_mapping_percentage', 0):.1f}%")
        
    except httpx.HTTPError as e:
        print(f"\n❌ HTTP Error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    print("Enhanced Employee-GitHub Mapping Tool")
    print("This tool uses advanced matching algorithms to map DarwinBox employees to GitHub contributors")
    print()
    asyncio.run(main())