# DarwinBox Integration

This document describes the DarwinBox HR system integration for the Copilot Backend.

## Overview

The DarwinBox integration allows you to:
- Sync employee data from DarwinBox HR system
- Map DarwinBox employees to GitHub accounts
- View organizational hierarchy and team structures
- Analyze team skills based on GitHub contributions
- Manage employee-GitHub mappings

## Configuration

### Environment Variables

Add the following to your `.env` file:

```env
# DarwinBox API Configuration
DARWINBOX_BASE_URL=https://interviewbit.darwinbox.in
DARWINBOX_API_KEY=your_api_key_here
DARWINBOX_DATASET_KEY=your_dataset_key_here

# Authentication (choose one method)
# Method 1: Basic Auth header
DARWINBOX_BASIC_AUTH=base64_encoded_credentials

# Method 2: Username/Password
DARWINBOX_USERNAME=your_username
DARWINBOX_PASSWORD=your_password
```

### Database Migration

Run the migration to create DarwinBox tables:

```bash
cd backend
alembic upgrade head
```

## API Endpoints

### Employee Sync

#### Sync All Employees
```http
POST /api/v1/darwinbox/sync-employees
Authorization: Bearer <token>

{
  "sync_type": "full",
  "include_inactive": false
}
```

#### Sync Specific Employees
```http
POST /api/v1/darwinbox/sync-employees
Authorization: Bearer <token>

{
  "sync_type": "specific",
  "employee_ids": ["EMP001", "EMP002"],
  "include_inactive": false
}
```

### Employee Management

#### List Employees
```http
GET /api/v1/darwinbox/employees?skip=0&limit=100&search=john&department=Engineering
Authorization: Bearer <token>
```

Query Parameters:
- `skip`: Pagination offset (default: 0)
- `limit`: Number of results (default: 100, max: 100)
- `search`: Search by name, email, or employee ID
- `department`: Filter by department
- `location`: Filter by location
- `has_github_mapping`: Filter by GitHub mapping status (true/false)
- `is_manager`: Filter managers only (true/false)
- `employment_status`: Filter by status (active/inactive/terminated)

#### Get Employee Details
```http
GET /api/v1/darwinbox/employees/{employee_id}
Authorization: Bearer <token>
```

### GitHub Mapping

#### Map Employee to GitHub
```http
POST /api/v1/darwinbox/map-employee
Authorization: Bearer <token>

{
  "darwinbox_employee_id": "uuid-here",
  "github_username": "johndoe",
  "verification_method": "manual",
  "verification_notes": "Verified via email"
}
```

#### Update Mapping
```http
PUT /api/v1/darwinbox/map-employee/{mapping_id}
Authorization: Bearer <token>

{
  "github_username": "john-doe-new",
  "mapping_verified": true,
  "verification_method": "api_verified"
}
```

#### Delete Mapping
```http
DELETE /api/v1/darwinbox/map-employee/{mapping_id}
Authorization: Bearer <token>
```

#### Auto-Map Based on Email
```http
POST /api/v1/darwinbox/auto-map-employees
Authorization: Bearer <token>
```

This endpoint automatically maps DarwinBox employees to GitHub accounts based on email matching.

### Team Management

#### Get My Team
```http
GET /api/v1/darwinbox/my-team?include_skills=true
Authorization: Bearer <token>
```

Returns the team hierarchy for the current user (must be a manager).

#### Get Team by Manager ID
```http
GET /api/v1/darwinbox/team/{manager_darwinbox_id}?include_skills=true
Authorization: Bearer <token>
```

### Utility Endpoints

#### Get Departments
```http
GET /api/v1/darwinbox/departments
Authorization: Bearer <token>
```

#### Get Locations
```http
GET /api/v1/darwinbox/locations
Authorization: Bearer <token>
```

#### Get Statistics
```http
GET /api/v1/darwinbox/stats
Authorization: Bearer <token>
```

## Data Models

### DarwinBoxEmployee
- `darwinbox_id`: Unique employee ID from DarwinBox
- `employee_code`: Employee code/number
- `full_name`: Employee full name
- `email`: Employee email address
- `designation`: Job title
- `department`: Department name
- `location`: Work location
- `reporting_manager_id`: Manager's DarwinBox ID
- `is_manager`: Whether employee is a manager
- `employment_status`: active/inactive/terminated
- `github_mapping`: Relationship to GitHub account mapping

### EmployeeGitHubMapping
- `darwinbox_employee_id`: Reference to DarwinBox employee
- `github_username`: GitHub username
- `github_id`: GitHub user ID (optional)
- `mapping_verified`: Whether mapping is verified
- `verification_method`: email_match/manual/api_verified
- `verification_notes`: Additional notes about verification

### TeamStructure
- `team_id`: Unique team identifier
- `team_name`: Team name
- `team_level`: Hierarchy level (1 = top level)
- `parent_team_id`: Parent team ID
- `manager_darwinbox_id`: Team manager's DarwinBox ID
- `total_members`: Number of team members

## Integration Flow

1. **Initial Setup**
   - Configure environment variables
   - Run database migrations

2. **Employee Sync**
   - Use `/sync-employees` to import employee data
   - This creates/updates DarwinBoxEmployee records

3. **GitHub Mapping**
   - Use `/auto-map-employees` for automatic email-based mapping
   - Manually map remaining employees using `/map-employee`

4. **Team Analysis**
   - Managers can view their teams with `/my-team`
   - Skill analysis integrates with GitHub contribution data

## Security Considerations

- Only superusers can sync employee data
- Employee data is encrypted at rest
- API keys and credentials are stored as environment variables
- All endpoints require authentication
- Sensitive employee data (phone numbers, etc.) can be restricted

## Troubleshooting

### Common Issues

1. **Sync Fails**
   - Check API credentials
   - Verify network connectivity to DarwinBox
   - Check API rate limits

2. **Mapping Issues**
   - Ensure GitHub contributors are synced first
   - Verify email addresses match
   - Check for typos in GitHub usernames

3. **Team Hierarchy Issues**
   - Ensure manager IDs are correctly set in DarwinBox
   - Verify all managers are synced
   - Check for circular references

### Logs

Check application logs for detailed error messages:
```bash
tail -f backend/backend.log
```

## Best Practices

1. **Regular Syncs**
   - Schedule daily syncs for active employees
   - Weekly full syncs including inactive employees

2. **Mapping Verification**
   - Verify auto-mapped accounts
   - Document manual mappings with notes

3. **Data Privacy**
   - Limit access to sensitive endpoints
   - Regularly audit access logs
   - Comply with data protection regulations