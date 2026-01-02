# Tab Lock Status Table - API Endpoint Fix

## Issue Fixed
The "🔒 PepHaul Entry Tab Lock Status" table in the Admin Panel was showing "Unknown" status and "Error" for all tabs due to incorrect API endpoint calls.

## Root Cause
The JavaScript in `templates/admin.html` was calling non-existent endpoints:
- **Wrong GET endpoint:** `/api/admin/tab-lock-status?tab_name=...` (404 error)
- **Wrong POST endpoint:** `/api/admin/tab-lock-status` (404 error)
- **Wrong response field:** Expected `lockData.message` instead of `lockData.lock_message`

## Solution
Updated the JavaScript functions to use the correct existing endpoint:

### File Changed: `templates/admin.html`

**1. Fixed `loadTabLockStatusTable()` function (line 3814):**
```javascript
// BEFORE (Wrong - 404 error):
const lockResponse = await fetch(`/api/admin/tab-lock-status?tab_name=${encodeURIComponent(tab)}`, {
    credentials: 'same-origin'
});
const lockData = await lockResponse.json();
const lockMessage = lockData.message || '';

// AFTER (Correct - uses existing endpoint):
const lockResponse = await fetch(`/api/admin/tab-settings?tab_name=${encodeURIComponent(tab)}`, {
    credentials: 'same-origin'
});
const lockData = await lockResponse.json();
const lockMessage = lockData.lock_message || '';
```

**2. Fixed `toggleTabLock()` function (line 3875):**
```javascript
// BEFORE (Wrong - 404 error):
const response = await fetch('/api/admin/tab-lock-status', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        tab_name: tabName,
        is_locked: shouldLock,
        message: lockMessage  // Wrong field name
    })
});

// AFTER (Correct - uses existing endpoint):
const response = await fetch('/api/admin/tab-settings', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        tab_name: tabName,
        is_locked: shouldLock,
        lock_message: lockMessage  // Correct field name
    })
});
```

## Correct Endpoint
**Route:** `/api/admin/tab-settings`
- **GET Method:** Fetch settings for a specific tab (requires `tab_name` query parameter)
  - Response: `{ success: true, tab_name, supplier, is_locked, lock_message }`
- **POST Method:** Update settings for a specific tab
  - Body: `{ tab_name, supplier?, is_locked?, lock_message? }`
  - Response: `{ success: true, message }`

## What Works Now
✅ **Tab Lock Status Table displays correctly:**
- Shows "🔒 Locked" or "🔓 Open" status for each PepHaul Entry tab
- Shows lock message (if set)
- "🔒 Lock" button locks the tab
- "🔓 Unlock" button unlocks the tab
- Table refreshes after toggle

✅ **No more console errors:**
- No more 404 errors for `/api/admin/tab-lock-status`
- No more JSON parsing errors
- Clean console logs

## Testing
1. **Open Admin Panel:** Navigate to admin page
2. **Check console:** No 404 errors should appear
3. **View table:** "🔒 PepHaul Entry Tab Lock Status" table should show correct status for all tabs
4. **Toggle lock:** Click "🔒 Lock" or "🔓 Unlock" button
5. **Verify:** Status should update and table should refresh

## Commit
- **Commit:** `b6eb51e`
- **Message:** "Fix: Correct API endpoint for tab lock status table"
- **Date:** 2025-01-03

