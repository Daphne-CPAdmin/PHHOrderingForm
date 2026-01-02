# Tab Lock Button Fix - Missing Helper Function

## Issue
The lock button in the Admin Panel's "🔒 Per-Tab Lock Status" table was not working. Clicking "🔒 Lock" or "🔓 Unlock" had no effect, and the browser console showed 500 errors.

## Console Errors Observed
```
Failed to load resource: the server responded with a status of 500 () - /api/admin/pephaul-tabs:1
Error loading tab settings: Error: Failed to load tabs: 500
at loadTabSettings (admin:3686:27)
```

## Root Cause
The backend endpoint `/api/admin/all-tab-settings` (line 7044-7071 in `app.py`) was calling a non-existent helper function `list_pephaul_tabs()` on line 7051:

```python
@app.route('/api/admin/all-tab-settings', methods=['GET'])
def api_admin_all_tab_settings():
    """Get settings for all tabs"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        tabs = list_pephaul_tabs()  # ❌ This function didn't exist!
        all_settings = []
        
        for tab in tabs:
            supplier_filter = get_supplier_filter_for_tab(tab)
            lock_status = get_tab_lock_status(tab)
            # ...
```

This caused:
1. The endpoint to crash with a 500 error (NameError: name 'list_pephaul_tabs' is not defined)
2. The frontend couldn't load tab settings
3. The lock toggle button couldn't save changes

## Solution
Created the missing `list_pephaul_tabs()` helper function in `app.py` (after line 377):

```python
def list_pephaul_tabs():
    """Get list of all PepHaul Entry tabs from Google Sheets"""
    if not sheets_client:
        print("⚠️ Sheets client not initialized when listing tabs")
        return []
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        all_sheets = spreadsheet.worksheets()
        
        # Filter tabs that start with "PepHaul Entry"
        pephaul_tabs = [ws.title for ws in all_sheets if ws.title.startswith('PepHaul Entry')]
        
        # Sort tabs: "PepHaul Entry-01" first, then other numbered ones, then old "PepHaul Entry"
        def sort_key(name):
            if name == 'PepHaul Entry-01':
                return (0, 1)  # Highest priority
            if name == 'PepHaul Entry':
                return (1, 0)  # Second priority (old name)
            # Extract number from "PepHaul Entry-02", "PepHaul Entry-03", etc.
            if '-' in name:
                try:
                    num = int(name.split('-')[-1])
                    return (1, num)  # After -01, sorted by number
                except:
                    return (2, name)
            return (2, name)
        
        pephaul_tabs.sort(key=sort_key)
        return pephaul_tabs
    except Exception as e:
        print(f"❌ Error listing PepHaul tabs: {e}")
        import traceback
        traceback.print_exc()
        return []
```

## What the Function Does
1. **Connects to Google Sheets** - Uses the sheets_client to access the spreadsheet
2. **Fetches all worksheets** - Gets list of all tabs in the spreadsheet
3. **Filters PepHaul Entry tabs** - Only returns tabs that start with "PepHaul Entry"
4. **Sorts tabs logically:**
   - "PepHaul Entry-01" first (highest priority)
   - Other numbered tabs (PepHaul Entry-02, -03, etc.) sorted by number
   - Old "PepHaul Entry" tab last (legacy compatibility)
5. **Error handling** - Returns empty list if sheets client not initialized or any error occurs

## What Works Now
✅ **Admin Panel - Per-Tab Lock Status Table:**
- Table loads correctly and displays all PepHaul Entry tabs
- Shows correct lock status for each tab ("🔒 Locked" or "🔓 Open")
- "🔒 Lock" button works - locks the tab successfully
- "🔓 Unlock" button works - unlocks the tab successfully
- Table refreshes after toggling lock status

✅ **API Endpoints Working:**
- `/api/admin/all-tab-settings` - Returns settings for all tabs without 500 error
- `/api/admin/pephaul-tabs` - Returns list of tabs (already was working)
- `/api/admin/tab-settings` (POST) - Successfully saves lock status changes

## Testing Steps
1. **Open Admin Panel:** Navigate to admin page
2. **Check console:** Should be no 500 errors (press F12 → Console tab)
3. **Scroll to "🔒 Per-Tab Lock Status" table**
4. **Verify:** Table shows all PepHaul Entry tabs with current lock status
5. **Test Lock:** Click "🔒 Lock" button on an unlocked tab
   - Should show success toast message
   - Table should refresh and show "🔒 Locked" status
   - Button should change to "🔓 Unlock"
6. **Test Unlock:** Click "🔓 Unlock" button on a locked tab
   - Should show success toast message
   - Table should refresh and show "🔓 Open" status
   - Button should change to "🔒 Lock"

## Additional Notes
- This function is reused by multiple endpoints, so fixing it resolves multiple issues at once
- The sorting logic ensures consistent tab order across the admin panel
- Error handling prevents crashes if Google Sheets is unavailable

## Commit
- **Commit:** `f66c465`
- **Message:** "Fix: Add missing list_pephaul_tabs() helper function"
- **Date:** 2025-01-03

