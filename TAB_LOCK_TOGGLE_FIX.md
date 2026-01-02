# Tab Lock Toggle Not Updating - FIX

## Problem

User reports: "Google Sheet saved lock status as Yes, but the toggle won't change in the admin panel. Customer panel remains open."

**Symptoms:**
- Click "🔒 Lock" button in admin panel
- Google Sheets "Settings" tab shows "Yes"
- But toggle button in admin panel doesn't update
- Customer panel still shows form as open

## Root Cause

**Cache timing issue:**

1. Admin clicks "🔒 Lock" → Calls `toggle TabLock('PepHaul Entry-02', true)`
2. Backend saves to Google Sheets via `set_tab_lock_status()` ✅
3. Backend calls `clear_cache('per_tab_lock_status')` ✅
4. Frontend calls `loadTabLockStatusTable()` to refresh UI
5. **PROBLEM:** `loadTabLockStatusTable()` fetches lock status via GET `/api/admin/tab-settings`
6. GET endpoint calls `get_tab_lock_status(tab_name)` which uses **60-second cache**
7. Cache was just cleared, but `get_cached()` immediately fetches fresh data and **caches it again**
8. The issue: If Google Sheets write is async or delayed, the fresh fetch might still read old data ("No") and cache it for 60 seconds

**The real issue:** Race condition between:
- Writing to Google Sheets
- Clearing cache
- Reading from Google Sheets (might still see old value)

## Solution

**Option 1: Return updated status directly from POST endpoint**
Instead of refetching, have the POST endpoint return the new status immediately.

**Option 2: Force cache bypass after updates**
Add a timestamp parameter to force fresh reads after updates.

**Option 3: Reduce cache duration to 0 seconds immediately after updates**
Temporarily disable caching right after updates.

**Best Solution: Option 1** - Return status directly, no need to refetch.

## Implementation

### Change 1: Update POST endpoint to return lock status

**File:** `app.py` (lines 7063-7095)

**BEFORE:**
```python
else:  # POST
    # Update tab settings
    data = request.json or {}
    tab_name = data.get('tab_name', '').strip()
    supplier = data.get('supplier', '').strip()
    is_locked = data.get('is_locked', False)
    lock_message = data.get('lock_message', '')
    
    try:
        # Update supplier filter
        if supplier:
            set_supplier_filter_for_tab(tab_name, supplier)
        
        # Update lock status (this clears per_tab_lock_status cache internally)
        set_tab_lock_status(tab_name, is_locked, lock_message)
        
        # Clear caches
        clear_cache('per_tab_lock_status')
        clear_cache_prefix('orders_')
        clear_cache_prefix('inventory_')
        
        return jsonify({
            'success': True,
            'tab_name': tab_name,
            'supplier': supplier
        })
```

**AFTER:**
```python
else:  # POST
    # Update tab settings
    data = request.json or {}
    tab_name = data.get('tab_name', '').strip()
    supplier = data.get('supplier', '').strip()
    is_locked = data.get('is_locked', False)
    lock_message = data.get('lock_message', '')
    
    try:
        # Update supplier filter
        if supplier:
            set_supplier_filter_for_tab(tab_name, supplier)
        
        # Update lock status (this clears per_tab_lock_status cache internally)
        set_tab_lock_status(tab_name, is_locked, lock_message)
        
        # Clear caches
        clear_cache('per_tab_lock_status')
        clear_cache_prefix('orders_')
        clear_cache_prefix('inventory_')
        
        # Return the updated status immediately (no need to refetch)
        return jsonify({
            'success': True,
            'tab_name': tab_name,
            'supplier': supplier,
            'is_locked': is_locked,
            'lock_message': lock_message
        })
```

### Change 2: Update frontend to use returned status

**File:** `templates/admin.html` (lines 3887-3914)

**BEFORE:**
```javascript
async function toggleTabLock(tabName, shouldLock) {
    try {
        const lockMessage = shouldLock ? `#${tabName.replace('PepHaul Entry-', 'PepHaul')} is currently locked...` : '';
        
        const response = await fetch('/api/admin/tab-settings', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tab_name: tabName,
                is_locked: shouldLock,
                lock_message: lockMessage
            })
        });
        
        const result = await response.json();
        if (result.success) {
            showToast(`✅ ${tabName} ${shouldLock ? 'locked' : 'unlocked'} successfully`);
            // Reload the table
            await loadTabLockStatusTable();
        }
    }
}
```

**AFTER:**
```javascript
async function toggleTabLock(tabName, shouldLock) {
    try {
        const lockMessage = shouldLock ? `#${tabName.replace('PepHaul Entry-', 'PepHaul')} is currently locked...` : '';
        
        const response = await fetch('/api/admin/tab-settings', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tab_name: tabName,
                is_locked: shouldLock,
                lock_message: lockMessage
            })
        });
        
        const result = await response.json();
        if (result.success) {
            showToast(`✅ ${tabName} ${shouldLock ? 'locked' : 'unlocked'} successfully`);
            
            // Update UI immediately with returned status (no refetch needed)
            const tbody = document.getElementById('tab-lock-status-tbody');
            if (tbody) {
                // Find the row for this tab and update it
                const rows = tbody.querySelectorAll('tr');
                for (const row of rows) {
                    const tabCell = row.querySelector('td:first-child');
                    if (tabCell && tabCell.textContent.trim() === tabName) {
                        // Update status cell
                        const statusCell = row.querySelector('td:nth-child(2)');
                        if (statusCell) {
                            statusCell.innerHTML = result.is_locked
                                ? '<span style="display: inline-flex; align-items: center; gap: 0.25rem; padding: 0.25rem 0.75rem; background: #fecaca; color: #991b1b; border-radius: 6px; font-size: 0.8rem; font-weight: 600;">🔒 Locked</span>'
                                : '<span style="display: inline-flex; align-items: center; gap: 0.25rem; padding: 0.25rem 0.75rem; background: #d1fae5; color: #065f46; border-radius: 6px; font-size: 0.8rem; font-weight: 600;">🔓 Open</span>';
                        }
                        
                        // Update button cell
                        const buttonCell = row.querySelector('td:nth-child(3)');
                        if (buttonCell) {
                            buttonCell.innerHTML = result.is_locked
                                ? `<button class="btn-sm" style="background: #10b981; color: white; padding: 0.5rem 1rem;" onclick="toggleTabLock('${tabName}', false)">🔓 Unlock</button>`
                                : `<button class="btn-sm" style="background: #f472b6; color: white; padding: 0.5rem 1rem;" onclick="toggleTabLock('${tabName}', true)">🔒 Lock</button>`;
                        }
                        break;
                    }
                }
            }
        }
    }
}
```

## Testing

1. Open admin panel → Scroll to "Per-Tab Lock Status"
2. Click "🔒 Lock" on "PepHaul Entry-02"
3. **Expected:** Button immediately changes to "🔓 Unlock", status shows "🔒 Locked"
4. Check Google Sheets "Settings" tab → Should show "Yes"
5. Open customer panel (in incognito/different browser) → Should show lock message
6. Click "🔓 Unlock" → Should immediately show "🔒 Lock", status shows "🔓 Open"

## Why This Works

- ✅ No refetching from API (avoids cache race condition)
- ✅ POST endpoint returns updated status directly
- ✅ Frontend updates UI immediately with returned data
- ✅ No 60-second cache delay
- ✅ Works even if Google Sheets write is slow

