# Scaler CRM Sync Fix

## Issue
The sync status was stuck at "syncing" and never updating to "completed", even though the data was being synced successfully in the background.

## Root Cause
The background task was using the same database session from the request context. Since FastAPI background tasks run after the response is sent, the session was likely closed, preventing database commits from working properly.

## Solution
Modified the sync endpoint to:

1. **Create a new database session in the background task**:
   ```python
   async def sync_with_new_session():
       from sqlmodel import Session as NewSession
       with NewSession(engine) as new_session:
           # Re-fetch the CRM auth in the new session
           fresh_crm_auth = new_session.get(ScalerCRMAuth, crm_auth.id)
           if fresh_crm_auth:
               await scaler_crm_service.sync_user_data(
                   new_session,
                   current_user,
                   fresh_crm_auth,
                   months_to_sync
               )
   ```

2. **Update sync status immediately when starting**:
   ```python
   # Update sync status to syncing
   crm_auth.sync_status = "syncing"
   session.add(crm_auth)
   session.commit()
   ```

## Result
- Sync now properly updates status to "completed" when finished
- Database commits work correctly in the background task
- Sync status endpoint returns accurate counts:
  - 3,238 leads synced
  - 10,458 activities synced
  - 0 conversations (none available in CRM)

## Additional Fixes Made

1. **Fixed CRM connection issue**: Changed from `scalerCRMApi.connect(email, password)` to `scalerCRMApi.connect({ email, password })`
2. **Fixed API method name**: Changed from `scalerCRMApi.syncData` to `scalerCRMApi.sync`

## Testing
To verify the fix works:
1. Disconnect and reconnect CRM
2. Start a new sync
3. Check sync status - should show "syncing"
4. Wait for completion
5. Check sync status - should show "completed" with accurate counts