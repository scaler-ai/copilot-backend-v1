# Backend API Implementation for Team Analysis

## Overview
This document describes the backend API implementation for the Team Analysis feature, which allows sales managers to analyze their team's performance using data from Darwinbox (team structure) and Scaler CRM (performance metrics).

## API Endpoints Implemented

### 1. Darwinbox Endpoints

#### GET /api/v1/darwinbox/me
- **Purpose**: Get current user's Darwinbox employee information
- **Authentication**: Required (JWT)
- **Response**: Employee details including manager status
```json
{
  "id": "uuid",
  "darwinbox_id": "DB123",
  "full_name": "John Doe",
  "email": "john@example.com",
  "is_manager": true,
  "department": "Sales",
  "designation": "Sales Manager"
}
```

#### GET /api/v1/darwinbox/my-team
- **Purpose**: Get team members for the current manager
- **Authentication**: Required (JWT + must be a manager)
- **Query Parameters**: 
  - `include_skills`: boolean (default: true)
- **Response**: List of team members with optional skill data
```json
[
  {
    "id": "uuid",
    "full_name": "Jane Smith",
    "email": "jane@example.com",
    "designation": "Sales Executive",
    "department": "Sales",
    "has_github_mapping": true,
    "skills": [
      {
        "skill_id": "sales_communication",
        "skill_name": "Sales Communication",
        "inferred_level": 4,
        "confidence_score": 85
      }
    ]
  }
]
```

### 2. Scaler CRM Endpoints

#### GET /api/v1/scaler-crm/team-performance
- **Purpose**: Get aggregated team performance metrics
- **Authentication**: Required (JWT + must be a manager)
- **Query Parameters**:
  - `period_months`: integer (1-12, default: 3)
- **Response**: Team performance data with member metrics and insights
```json
{
  "team_stats": {
    "total_members": 8,
    "members_with_crm": 6,
    "avg_overall_score": 68.5,
    "avg_conversion_rate": 12.5,
    "total_activities": 450,
    "total_leads": 120
  },
  "member_performance": [
    {
      "member_id": "uuid",
      "member_name": "Jane Smith",
      "member_email": "jane@example.com",
      "has_crm_connected": true,
      "performance": {
        "overall_score": 75.0,
        "conversion_rate": 15.2,
        "total_activities": 85,
        "total_leads": 20,
        "avg_response_time": 4.5,
        "activity_breakdown": {
          "email": 40,
          "call": 30,
          "meeting": 15
        },
        "skill_ratings": [...]
      }
    }
  ],
  "skill_aggregates": {
    "sales_communication": {
      "skill_name": "Sales Communication",
      "avg_level": 3.5,
      "coverage": 80
    }
  },
  "team_insights": {
    "strengths": [
      "Strong team capabilities in Communication, Relationship Building"
    ],
    "improvements": [
      "2 team members need to connect their CRM",
      "Team-wide training needed for Closing Skills"
    ],
    "performance_distribution": {
      "high_performers": 2,
      "average_performers": 3,
      "low_performers": 1,
      "no_data": 2
    }
  }
}
```

## Implementation Details

### 1. Service Layer Updates

#### sales_analysis_service.py
Added new method `analyze_team_performance` that:
- Validates user is a manager via Darwinbox
- Fetches all team members from Darwinbox
- For each team member with CRM connected:
  - Calculates performance metrics
  - Retrieves skill ratings
  - Computes overall scores
- Aggregates team-wide statistics
- Generates team insights using existing analysis patterns

### 2. Route Integration

#### darwinbox.py
- Added `/me` endpoint for current user's employee info
- Updated `/my-team` to return list format expected by frontend
- Includes skill data when available via GitHub mapping

#### scaler_crm.py  
- Updated `/team-performance` from placeholder to full implementation
- Calls `analyze_team_performance` service method
- Handles authentication and manager validation

### 3. Data Flow

1. **Authentication**: User must be logged in with JWT token
2. **Manager Verification**: 
   - System checks if user is mapped to Darwinbox employee
   - Verifies employee has `is_manager` flag
3. **Team Data Retrieval**:
   - Fetches direct reports from Darwinbox
   - For each team member, checks CRM connection
4. **Performance Analysis**:
   - Uses existing performance metrics calculation
   - Leverages skill rating system
   - Aggregates data across team
5. **Insights Generation**:
   - Identifies team strengths and gaps
   - Provides actionable recommendations

## Error Handling

- **403 Forbidden**: User is not a manager
- **404 Not Found**: User not mapped to Darwinbox employee  
- **500 Internal Error**: Analysis failure with detailed logging

## Testing with Mock Data

The frontend includes comprehensive mock data fallback:
- Mock Darwinbox employee and team data
- Mock Scaler CRM performance metrics
- Allows full feature testing without backend

## Security Considerations

- All endpoints require authentication
- Manager status verified before accessing team data
- Employee PII protected by access controls
- CRM credentials encrypted in database

## Future Enhancements

1. **Caching**: Add Redis caching for team performance data
2. **Async Processing**: Move heavy analysis to background tasks
3. **Webhooks**: Real-time updates when team data changes
4. **Export**: PDF/CSV export endpoints for reports
5. **Historical Tracking**: Store and compare team performance over time