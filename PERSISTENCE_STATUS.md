# PepHaul Entry Tab Persistence Status

## ✅ ALREADY IMPLEMENTED - Persistence is WORKING

Your system **already has full persistence** for both lock status and supplier assignments. Here's how it works:

---

## 🔒 Per-Tab Lock Status Persistence

### Storage: Google Sheets "Settings" Tab

**Location:** Google Sheets → "Settings" tab
**Format:** Each PepHaul Entry tab has a dedicated row

| Setting | Tab Name | Value | Message | Updated |
|---------|----------|-------|---------|---------|
| Tab Lock Status | PepHaul Entry-01 | Yes/No | Lock message text | 2025-01-03 10:30:45 |
| Tab Lock Status | PepHaul Entry-02 | Yes/No | Lock message text | 2025-01-03 10:31:12 |

### How It Works

**When Admin Locks a Tab:**
1. Admin clicks "🔒 Lock" button in "Per-Tab Lock Status" section
2. JavaScript calls `/api/admin/tab-settings` POST endpoint
3. Backend function `set_tab_lock_status()` saves to Google Sheets "Settings" tab:
   - Setting: "Tab Lock Status"
   - Tab Name: e.g., "PepHaul Entry-02"
   - Value: "Yes" (locked) or "No" (unlocked)
   - Message: Custom lock message (e.g., "#PepHaul02 is currently locked...")
   - Updated: Timestamp

4. Clears all related caches so changes take effect immediately

**When Customer Views Form:**
1. Backend calls `get_tab_lock_status(current_tab)`
2. Reads from Google Sheets "Settings" tab (cached for 60 seconds)
3. Returns lock status and message
4. If locked, customer sees lock message instead of order form

**Persistence Guarantees:**
- ✅ Survives page refreshes
- ✅ Survives server restarts
- ✅ Survives multiple days
- ✅ Only admin can unlock by toggling back to "🔓 Open"

### Code References

**Backend (app.py):**
- `_fetch_per_tab_lock_status()` (lines 838-876): Reads from Google Sheets
- `set_tab_lock_status()` (lines 884-933): Saves to Google Sheets
- `get_tab_lock_status()` (lines 878-882): Gets status with caching

**Frontend (admin.html):**
- Per-Tab Lock Status section (around line 3900+)
- Lock/Unlock buttons that call `/api/admin/tab-settings`

---

## 🏷️ Supplier Assignment Persistence

### Storage: Local JSON File + In-Memory

**Location:** `data/pephaul_settings.json`
**Format:** JSON file with supplier filters per tab

```json
{
  "supplier_filters": {
    "PepHaul Entry-01": "Supplier A",
    "PepHaul Entry-02": "Supplier B"
  },
  "current_pephaul_tab": "PepHaul Entry-02"
}
```

### How It Works

**When Admin Assigns Supplier:**
1. Admin selects supplier from dropdown in "PepHaul Entry Tab Settings"
2. JavaScript calls `/api/admin/tab-settings` POST endpoint
3. Backend function `set_supplier_filter_for_tab()` saves to both:
   - **Memory:** `_pephaul_supplier_filter` dict
   - **Persistent file:** `data/pephaul_settings.json`

4. Settings file is written immediately using `_save_settings()`

**When Server Starts:**
1. Backend calls `_load_settings()` on startup
2. Loads `supplier_filters` from `data/pephaul_settings.json`
3. Populates `_pephaul_supplier_filter` dict
4. All tabs remember their assigned suppliers

**Persistence Guarantees:**
- ✅ Survives page refreshes
- ✅ Survives server restarts (loaded from file on startup)
- ✅ Survives multiple days
- ✅ Only admin can change by selecting different supplier

### Code References

**Backend (app.py):**
- `_load_settings()` (lines 44-52): Loads from JSON file on startup
- `_save_settings()` (lines 54-64): Saves to JSON file
- `set_supplier_filter_for_tab()` (lines 349-365): Saves supplier assignment
- `get_supplier_filter_for_tab()` (lines 345-347): Gets assigned supplier

**Settings File:**
- Path: `data/pephaul_settings.json`
- Created automatically on first save
- Contains: `supplier_filters`, `current_pephaul_tab`

---

## 🔍 Testing Your Persistence

### Test Lock Persistence:
1. Open Admin Panel → Scroll to "Per-Tab Lock Status"
2. Click "🔒 Lock" on "PepHaul Entry-02"
3. Check Google Sheets → "Settings" tab → Should see row with:
   - Setting: "Tab Lock Status"
   - Tab Name: "PepHaul Entry-02"
   - Value: "Yes"
4. Refresh admin panel → Lock status should persist
5. Restart server → Lock status should still persist

### Test Supplier Persistence:
1. Open Admin Panel → Scroll to "PepHaul Entry Tab Settings"
2. Select "PepHaul Entry-02" tab
3. Choose supplier from dropdown (e.g., "Supplier B")
4. Click "Save Settings"
5. Check `data/pephaul_settings.json` file → Should contain:
   ```json
   {
     "supplier_filters": {
       "PepHaul Entry-02": "Supplier B"
     }
   }
   ```
6. Refresh admin panel → Supplier should persist
7. Restart server → Supplier should still persist

---

## 📝 If Settings File Doesn't Exist Yet

The `data/pephaul_settings.json` file is **created automatically** on first save. If it doesn't exist yet:

1. Open Admin Panel
2. Make ANY change to tab settings (assign supplier or lock/unlock)
3. File will be created automatically at `data/pephaul_settings.json`

---

## ✅ Summary

**You already have full persistence implemented!**

- **Lock Status:** Saved to Google Sheets "Settings" tab
- **Supplier Assignment:** Saved to `data/pephaul_settings.json`
- **Both survive:** Page refreshes, server restarts, multiple days
- **Both require admin action to change:** Only admin can toggle lock or change supplier

**No additional work needed!** Your persistence is already working. If you're seeing issues, it might be a caching problem (cache is 60 seconds for lock status).

---

## 🐛 Troubleshooting

**If lock status doesn't persist:**
- Check Google Sheets → "Settings" tab → Verify rows exist
- Check browser console for API errors
- Check server logs for "Error setting tab lock status"
- Cache duration is 60 seconds, so wait 1 minute and refresh

**If supplier doesn't persist:**
- Check `data/pephaul_settings.json` file exists
- Check file contains `supplier_filters` key
- Check browser console for API errors
- Check server logs for "Could not persist supplier filter"

**Common issues:**
- Google Sheets API not configured → Lock status won't save
- File permissions → Settings file can't be written
- Cache not cleared → Changes take up to 60 seconds to appear

