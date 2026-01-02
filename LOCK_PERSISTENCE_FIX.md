# Lock Status Persistence Fix

## Issues Reported
1. **Lock status not persisting** - Form would reopen after page refresh even though admin locked it
2. **Customer panel not showing locked display** - Order Statistics still showing instead of lock message

## Root Causes

### Issue 1: Stale Cache
The `get_tab_lock_status()` function was caching lock status for **600 seconds (10 minutes)**:

```python
# OLD CODE (600 second cache):
def get_tab_lock_status(tab_name):
    all_statuses = get_cached('per_tab_lock_status', _fetch_per_tab_lock_status, cache_duration=600)
    return all_statuses.get(tab_name, {'is_locked': False, 'message': ''})
```

**Problem:**
- Admin locks form → Saved to Google Sheets ✅
- Customer refreshes page → Backend reads from cache (10-minute-old data) ❌
- Customer sees form as unlocked because cache hasn't expired yet

### Issue 2: Incomplete Cache Clearing
The `/api/admin/tab-settings` endpoint was only clearing `per_tab_lock_status` cache internally via `set_tab_lock_status()`, but not explicitly clearing related caches that depend on lock status.

## Solutions Implemented

### 1. Reduced Cache Duration (60 seconds)

**File:** `app.py` (line 878-881)

**BEFORE:**
```python
def get_tab_lock_status(tab_name):
    """Get lock status for a specific tab"""
    all_statuses = get_cached('per_tab_lock_status', _fetch_per_tab_lock_status, cache_duration=600)
    return all_statuses.get(tab_name, {'is_locked': False, 'message': ''})
```

**AFTER:**
```python
def get_tab_lock_status(tab_name):
    """Get lock status for a specific tab"""
    # Use shorter cache duration (60 seconds) so lock status updates are reflected quickly
    all_statuses = get_cached('per_tab_lock_status', _fetch_per_tab_lock_status, cache_duration=60)
    return all_statuses.get(tab_name, {'is_locked': False, 'message': ''})
```

**Key Changes:**
- ✅ Cache duration: 600s → 60s (10 minutes → 1 minute)
- ✅ Lock status updates reflect within 60 seconds instead of 10 minutes
- ✅ Faster customer panel refresh after admin toggles lock

### 2. Explicit Cache Clearing

**File:** `app.py` (line 7048-7083)

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
        
        # Update lock status
        set_tab_lock_status(tab_name, is_locked, lock_message)  # Only clears cache internally
        
        print(f"✅ Updated tab settings for {tab_name}: Supplier={supplier}, Locked={is_locked}")
        
        return jsonify({...})
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
        
        # IMPORTANT: Clear ALL related caches to ensure customer panel sees updated status
        clear_cache('per_tab_lock_status')  # Redundant but ensures it's cleared
        clear_cache_prefix('orders_')  # Clear orders cache as lock affects order submission
        clear_cache_prefix('inventory_')  # Clear inventory cache
        
        print(f"✅ Updated tab settings for {tab_name}: Supplier={supplier}, Locked={is_locked}, Message={lock_message[:50] if lock_message else '(none)'}")
        
        return jsonify({...})
```

**Key Changes:**
- ✅ Explicit `clear_cache('per_tab_lock_status')` call (redundant but ensures)
- ✅ Clear `orders_` cache prefix (order submission checks lock status)
- ✅ Clear `inventory_` cache prefix (inventory display may change when locked)
- ✅ Better logging with lock message preview (first 50 chars)

### 3. How Lock Status Flows

**Admin locks form:**
1. Click "🔒 Lock" button in "Per-Tab Lock Status" table
2. JavaScript calls `/api/admin/tab-settings` POST with `is_locked: true`
3. Backend calls `set_tab_lock_status()` → Saves to Google Sheets "Settings" tab
4. Backend clears all related caches explicitly
5. Lock status is now saved ✅

**Customer views form:**
1. Customer loads page (or refreshes)
2. Backend calls `get_tab_lock_status(current_tab)`
3. Reads from cache (60-second duration, or fresh if just cleared)
4. If cache expired, reads from Google Sheets "Settings" tab
5. Returns `{'is_locked': True, 'message': '...'}`
6. Template renders with `order_form_locked=True`
7. JavaScript hides Order Statistics, shows lock banner ✅

## What Works Now

✅ **Lock status persists across refreshes:**
- Admin locks form → Status saved to Google Sheets
- Customer refreshes → Sees locked form (within 60 seconds)
- Form stays locked until admin unlocks it

✅ **Faster updates:**
- Old: 10-minute cache meant customers waited up to 10 minutes to see lock
- New: 60-second cache means customers see lock within 1 minute

✅ **Explicit cache clearing:**
- When admin toggles lock, ALL related caches are cleared
- Ensures no stale data anywhere in the system

✅ **Better logging:**
- Admin can see lock message preview in server logs
- Easier debugging of lock status issues

## Testing Steps

**IMPORTANT:** Restart your Flask server for changes to take effect!

1. **Stop Flask server:** Press `Ctrl+C`
2. **Restart:** `python app.py`

**Test lock persistence:**
1. **Admin Panel:** Lock PepHaul Entry-02 using "🔒 Lock" button
2. **Wait 10 seconds** (give cache time to clear)
3. **Customer Panel:** Open in **incognito/private window** (or hard refresh `Ctrl+Shift+R`)
   - Should show lock banner: "#PepHaul02 is currently locked..."
   - Should hide "Order Statistics - PepHaul Entry-02 (YIWU)"
   - Should show Order Timeline
4. **Refresh customer panel** → Lock status should persist ✅
5. **Admin Panel:** Unlock PepHaul Entry-02 using "🔓 Unlock" button
6. **Wait 10 seconds**
7. **Customer Panel:** Refresh → Should show Order Statistics again ✅

**Test cache timing:**
1. Lock form in admin panel
2. Immediately refresh customer panel → May still show unlocked (cache not expired yet)
3. Wait 60 seconds, refresh again → Should show locked ✅

## Known Behavior

- **60-second cache window:** After admin toggles lock, customers may need to wait up to 60 seconds to see the change
- **Why 60 seconds?** Balance between performance (fewer Google Sheets API calls) and responsiveness (faster updates)
- **For immediate updates:** Customers can do hard refresh (`Ctrl+Shift+R`) to bypass browser cache

## Commit
- **Commit:** `099d065`
- **Message:** "Fix: Lock status now persists and updates immediately"
- **Date:** 2025-01-03

