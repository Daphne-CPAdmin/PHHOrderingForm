# Cross-Device Tab Persistence Fix

## Problem
When opening the customer form from different devices (Desktop, Mobile, iPad), customers were seeing "PepHaul Entry-01" instead of the locked view set in the admin panel. This happened because:

1. **localStorage Priority Issue:** JavaScript was prioritizing browser's `localStorage` over the server's persistent locked view
2. **Stale Data:** Different devices had different cached values in `localStorage`
3. **Empty Cache:** New devices/browsers had empty `localStorage`, causing fallback to default values

## Root Cause

**Before Fix (line 2838 in index.html):**
```javascript
// Current PepHaul tab selection (synced from Admin Panel via postMessage)
let currentPepHaulTab = localStorage.getItem('currentPepHaulTab') || '';
```

This code:
- ❌ Checked localStorage FIRST (device-specific, not synced)
- ❌ Used empty string as fallback (caused issues downstream)
- ❌ Never initialized from server's persistent locked view on page load

**Result:**
- Desktop opens form → sees "PepHaul Entry-01" (cached in localStorage from last visit)
- Mobile opens form → sees "PepHaul Entry-01" (empty localStorage → falls back to default)
- Admin changes to "PepHaul Entry-02" → only updates server's persistent storage
- Customers on different devices still see old cached values until they manually refresh

## Solution

### 1. Initialize from Server on Every Page Load

**After Fix (index.html, ~line 2837):**
```javascript
// Current PepHaul tab selection - ALWAYS sync from server's locked view on load
// This ensures all devices (Desktop, Mobile, iPad) see the same locked view
let currentPepHaulTab = CURRENT_PEPHAUL_TAB;
// Update localStorage to match server's persistent setting
try {
    localStorage.setItem('currentPepHaulTab', currentPepHaulTab);
} catch (e) {
    console.warn('Could not sync currentPepHaulTab to localStorage:', e);
}
```

**Changes:**
- ✅ Initialize from server's value (`CURRENT_PEPHAUL_TAB`) on EVERY page load
- ✅ Update localStorage to MATCH server (instead of reading from localStorage first)
- ✅ All devices now sync to the same server-side persistent locked view

### 2. Update Order Lookup Logic

**Before:**
```javascript
const tabName = localStorage.getItem('currentPepHaulTab') || CURRENT_PEPHAUL_TAB || 'PepHaul Entry-01';
```

**After (index.html, ~line 4716):**
```javascript
// Get current tab name (always use server's locked view)
const tabName = currentPepHaulTab || CURRENT_PEPHAUL_TAB || 'PepHaul Entry-01';
```

**Changes:**
- ✅ Use `currentPepHaulTab` variable (synced from server on load)
- ✅ No longer reading from localStorage directly (prevents stale data)

### 3. Enhanced postMessage Handler

**Added comments to clarify flow (index.html, ~line 3099):**
```javascript
// Listen for tab/supplier changes from admin panel
// NOTE: Admin changes the locked view via admin panel → broadcasts to customer panels
// On page load, customer panels ALWAYS sync from server's persistent locked view
window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'tabSwitched') {
        const tabName = (event.data.tab_name || event.data.tabName || event.data.tab || '').trim();
        if (tabName) {
            // Admin changed the locked view - update current tab
            currentPepHaulTab = tabName;
            localStorage.setItem('currentPepHaulTab', currentPepHaulTab);
            ...
        }
    }
});
```

**Purpose:**
- ✅ Admin changes locked view → broadcasts to open customer panels via postMessage
- ✅ Customers opening form fresh → sync from server's persistent storage on page load
- ✅ Best of both worlds: real-time updates + persistent cross-device sync

## How It Works Now

### Flow 1: Customer Opens Form (Desktop)
1. Server loads persistent locked view from `data/pephaul_settings.json` → "PepHaul Entry-02"
2. Server renders template with `current_tab="PepHaul Entry-02"`
3. JavaScript initializes: `let currentPepHaulTab = CURRENT_PEPHAUL_TAB;` → "PepHaul Entry-02"
4. JavaScript updates localStorage to match: `localStorage.setItem('currentPepHaulTab', 'PepHaul Entry-02');`
5. Customer sees "PepHaul Entry-02" ✅

### Flow 2: Customer Opens Form (Mobile, Same Time)
1. Server loads persistent locked view from `data/pephaul_settings.json` → "PepHaul Entry-02"
2. Server renders template with `current_tab="PepHaul Entry-02"`
3. JavaScript initializes: `let currentPepHaulTab = CURRENT_PEPHAUL_TAB;` → "PepHaul Entry-02"
4. JavaScript updates localStorage to match: `localStorage.setItem('currentPepHaulTab', 'PepHaul Entry-02');`
5. Customer sees "PepHaul Entry-02" ✅

### Flow 3: Admin Changes Locked View (While Customers Have Form Open)
1. Admin changes locked view to "PepHaul Entry-03" in admin panel
2. Backend saves to `data/pephaul_settings.json` → "PepHaul Entry-03"
3. Admin panel broadcasts postMessage: `{type: 'tabSwitched', tab_name: 'PepHaul Entry-03'}`
4. Open customer panels receive message and update: `currentPepHaulTab = 'PepHaul Entry-03'`
5. localStorage updated to match: `localStorage.setItem('currentPepHaulTab', 'PepHaul Entry-03');`
6. All open customer panels switch to "PepHaul Entry-03" in real-time ✅

### Flow 4: Admin Changes Locked View (Customers Refresh/Open New)
1. Admin changes locked view to "PepHaul Entry-04" in admin panel
2. Backend saves to `data/pephaul_settings.json` → "PepHaul Entry-04"
3. Customer opens form fresh (Desktop, Mobile, iPad, any device)
4. Server loads from persistent storage → "PepHaul Entry-04"
5. JavaScript initializes from server: `currentPepHaulTab = CURRENT_PEPHAUL_TAB` → "PepHaul Entry-04"
6. Customer sees "PepHaul Entry-04" regardless of device ✅

## Key Benefits

### 1. Cross-Device Consistency
- ✅ Desktop, Mobile, iPad all see the same locked view
- ✅ No more device-specific cached values causing confusion
- ✅ Single source of truth: server's persistent storage

### 2. Real-Time Updates + Persistent Storage
- ✅ Customers with form open get real-time updates via postMessage
- ✅ Customers opening form fresh sync from persistent storage
- ✅ No manual refresh required for open forms
- ✅ Automatic sync for new sessions/devices

### 3. Robust Fallback
- ✅ If localStorage fails (privacy mode, quota exceeded), uses `currentPepHaulTab` variable
- ✅ Variable always initialized from server on page load
- ✅ Graceful error handling with console warnings

## Files Modified

1. **templates/index.html** (~line 2837-2845)
   - Changed `currentPepHaulTab` initialization to use server value first
   - Update localStorage to MATCH server (instead of reading from it)
   - Added comments clarifying cross-device sync behavior

2. **templates/index.html** (~line 4716)
   - Updated order lookup to use `currentPepHaulTab` variable (synced from server)
   - Removed direct localStorage reads (prevents stale data)

3. **templates/index.html** (~line 3099-3142)
   - Enhanced postMessage handler comments
   - Clarified admin → customer broadcast flow
   - Documented page load sync behavior

## Backend (No Changes Required)

The backend already had persistent storage working correctly:

1. **app.py** (lines 41-64): Persistent storage functions
   - `_load_settings()` - Reads from `data/pephaul_settings.json`
   - `_save_settings()` - Writes to `data/pephaul_settings.json`

2. **app.py** (line 66): Initialization from persistent storage
   ```python
   _settings = _load_settings()
   CURRENT_PEPHAUL_TAB = _settings.get('current_pephaul_tab', 'PepHaul Entry-01')
   ```

3. **app.py** (line 3245): Template rendering
   ```python
   return render_template('index.html', 
                        ...
                        current_tab=current_tab,
                        ...)
   ```

**The issue was NOT in the backend - it was in how the frontend prioritized localStorage over the server value.**

## Testing Checklist

### Test 1: Different Devices See Same View
1. ✅ Admin sets locked view to "PepHaul Entry-02"
2. ✅ Open form on Desktop → verify shows "PepHaul Entry-02"
3. ✅ Open form on Mobile → verify shows "PepHaul Entry-02"
4. ✅ Open form on iPad → verify shows "PepHaul Entry-02"
5. ✅ All devices should show the SAME locked view

### Test 2: Admin Changes Persist Across Devices
1. ✅ Admin changes locked view to "PepHaul Entry-03"
2. ✅ Refresh Desktop form → verify shows "PepHaul Entry-03"
3. ✅ Refresh Mobile form → verify shows "PepHaul Entry-03"
4. ✅ Open form on new device → verify shows "PepHaul Entry-03"

### Test 3: Real-Time Updates for Open Forms
1. ✅ Open form on Desktop (leave open)
2. ✅ Open admin panel in another tab
3. ✅ Change locked view to "PepHaul Entry-04"
4. ✅ Desktop form should update to "PepHaul Entry-04" immediately (no refresh needed)

### Test 4: Server Restart Persistence
1. ✅ Admin sets locked view to "PepHaul Entry-05"
2. ✅ Restart server
3. ✅ Open form on any device → verify shows "PepHaul Entry-05"
4. ✅ Setting should persist across server restarts

### Test 5: localStorage Cleared/Disabled
1. ✅ Open form, verify shows correct locked view
2. ✅ Clear browser localStorage
3. ✅ Refresh page → verify STILL shows correct locked view (syncs from server)
4. ✅ Try in private/incognito mode → verify shows correct locked view

## User Impact

### Before Fix
- ❌ "I set the view to Entry-02, but when I open from my phone it shows Entry-01"
- ❌ "Different devices show different views even though I locked it"
- ❌ "I need to manually refresh on every device to see the locked view"

### After Fix
- ✅ "All my devices show the same locked view automatically"
- ✅ "When I change the locked view in admin, everyone sees it on next page load"
- ✅ "No more confusion - the locked view persists across all devices"

## Technical Notes

### Why localStorage is Still Used
localStorage serves as a **secondary cache** for performance, but is now **synced FROM the server** instead of being the source of truth:

1. **Page Load:** Server value → JavaScript variable → localStorage
2. **Admin Changes:** Admin panel → postMessage → JavaScript variable → localStorage
3. **Order Lookups:** JavaScript variable (synced from server) → API calls

**Benefits:**
- Fast reads (no need to query server constantly)
- Synchronized with server on every page load
- Real-time updates via postMessage
- Graceful degradation if localStorage unavailable

### Cache-Control Headers
The backend already had cache-control headers to prevent browser caching (app.py, lines 3259-3262):

```python
response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
response.headers['Pragma'] = 'no-cache'
response.headers['Expires'] = '0'
```

This ensures customers always get the latest server-side data when loading the page.

## Related Documentation

- **PEPHAUL_DISPLAY_PERSISTENCE_FIX.md** - Original fix for persistence across sessions
- **SUPPLIER_LOCK_TABLE_FIX.md** - Supplier assignment persistence per tab
- **GLOBAL_VIEW_LOCK_ENHANCEMENT.md** - Admin panel UI enhancements for clarity

## Summary

This fix ensures the **locked display view persists across ALL devices** by:
1. ✅ Initializing from server's persistent storage on EVERY page load
2. ✅ Syncing localStorage FROM the server (not the other way around)
3. ✅ Using JavaScript variable as source of truth (synced from server)
4. ✅ Supporting real-time updates via postMessage for open forms
5. ✅ Providing robust fallback if localStorage unavailable

**Result:** Customers see the SAME locked view on Desktop, Mobile, iPad, and any device - no more confusion! 🎉

