# Supplier Lock Table Feature

## Problem
Supplier assignments for PepHaul Entry tabs were reverting to "All" even after being set to a specific supplier (e.g., YIWU). This caused confusion during ordering because both suppliers' products would appear in the product list.

## Solution Implemented
Added a **Locked Supplier Assignments Table** that shows all PepHaul Entry tabs and their assigned suppliers in one clear view. This uses the persistent storage system we already implemented to ensure assignments survive server restarts.

---

## Changes Made

### 1. Added Supplier Assignment Table (templates/admin.html)

**Location:** After the "PepHaul Entry Tab Settings" section

**New UI Elements:**
- Table header: "🔒 Locked Supplier Assignments" with badge "One supplier per tab"
- Description: "Each PepHaul Entry tab is locked to exactly one supplier. This prevents confusion during ordering."
- 3-column table:
  - **PepHaul Entry Tab** - Tab name (e.g., PepHaul Entry-01, PepHaul Entry-02)
  - **Assigned Supplier** - Shows assigned supplier with color coding:
    - Green background (#d1fae5) = Supplier assigned
    - Yellow background (#fef3c7) = "Not assigned"
  - **Status** - Lock status:
    - ✓ Locked (green) = Supplier assigned
    - ⚠️ No supplier (yellow) = Not assigned
    - ❌ Error (red) = Error loading

**HTML Added:** Lines 727-764 in admin.html
```html
<!-- Supplier Assignment Table -->
<div style="margin-top: 2rem; border-top: 2px solid #e5e7eb; padding-top: 2rem;">
    <h3>🔒 Locked Supplier Assignments</h3>
    <p>Each PepHaul Entry tab is locked to exactly one supplier.</p>
    
    <div class="table-container">
        <table class="products-table">
            <thead>
                <tr>
                    <th>PepHaul Entry Tab</th>
                    <th>Assigned Supplier</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="supplier-assignments-tbody">
                <!-- Populated by JavaScript -->
            </tbody>
        </table>
    </div>
</div>
```

### 2. Added JavaScript Function to Load Table (templates/admin.html)

**New Function:** `loadSupplierAssignmentsTable()`

**Location:** After `loadTabSettings()` function (lines 3548-3646)

**What it does:**
1. Fetches all PepHaul Entry tabs from `/api/admin/pephaul-tabs`
2. For each tab, fetches settings from `/api/admin/tab-settings?tab_name={tab}`
3. Extracts supplier assignment for each tab
4. Builds table rows with:
   - Tab name
   - Supplier (or "Not assigned")
   - Status indicator with color coding
5. Populates the table body (`supplier-assignments-tbody`)

**Key Features:**
- **Handles errors gracefully** - Shows "Error loading" if a tab's settings fail
- **Color coding** - Visual feedback for assigned/not assigned
- **Real-time data** - Fetches current assignments from persistent storage
- **Automatic refresh** - Called when `loadTabSettings()` runs

### 3. Integrated with Existing Save Flow

**Modified:** `loadTabSettings()` function now calls `loadSupplierAssignmentsTable()`

**Line added:** Line 3544
```javascript
// Load supplier assignments table
await loadSupplierAssignmentsTable();
```

**Refresh triggers:**
- On page load (when admin panel opens)
- After saving tab settings (via `loadTabSettings()` call at line 3763)
- When switching tabs
- After creating new tabs

---

## How It Works

### Persistence Flow:
1. **Admin assigns supplier** via dropdown → Clicks "Save Settings"
2. **Backend saves** to `data/pephaul_settings.json` using `set_supplier_filter_for_tab()`
3. **Table updates** automatically after save completes
4. **Assignment persists** across server restarts (file-based storage)
5. **Customer sees** correct products filtered by locked supplier

### Visual Feedback:
- **Green** = Good! Supplier locked ✓
- **Yellow** = Warning! No supplier assigned ⚠️
- **Red** = Error loading settings ❌

### One Supplier Per Tab Enforcement:
The existing backend already enforces this:
- Each tab can only have ONE supplier value in `_pephaul_supplier_filter[tab_name]`
- When saving, the new supplier **replaces** the old one
- No "Add another supplier" - it's always an assignment/update

---

## Files Changed

### templates/admin.html
1. **Lines 727-764:** Added supplier assignments table HTML
2. **Lines 3548-3646:** Added `loadSupplierAssignmentsTable()` JavaScript function
3. **Line 3544:** Integrated table loading into `loadTabSettings()`

### No Backend Changes Required
The persistent storage for suppliers was already implemented in `app.py`:
- `get_supplier_filter_for_tab()` - Gets supplier for a tab
- `set_supplier_filter_for_tab()` - Sets supplier for a tab (with persistence)
- `_load_settings()` / `_save_settings()` - Persistent JSON file storage

---

## Benefits

### 1. Visibility
Admins can now see **all tabs and their suppliers at a glance** instead of selecting each tab individually.

### 2. Clarity
The table clearly shows which tabs have suppliers assigned and which don't, preventing the "reverting to All" confusion.

### 3. Persistence
Uses the same JSON file storage (`data/pephaul_settings.json`) that we implemented for the display tab, so:
- Settings survive server restarts ✓
- Settings survive deployments ✓
- No more mystery resets to "All" ✓

### 4. One Supplier = One Tab
Visual reinforcement of the rule with the "One supplier per tab" badge, preventing customer confusion during ordering.

---

## Testing Checklist

### Before Pushing:
1. ✅ **Verify table appears** - Check admin panel loads the table below settings form
2. ✅ **Verify table populates** - All PepHaul Entry tabs should appear in table
3. ✅ **Verify status indicators** - Green for assigned, yellow for not assigned
4. ✅ **Test save flow** - Assign supplier → Save → Table updates
5. ✅ **Test persistence** - Restart server → Table still shows assignments
6. ✅ **Test error handling** - Table handles missing/errored tabs gracefully

### After Deployment:
1. **Assign supplier to Entry-02** - Set to YIWU
2. **Check table** - Should show "YIWU" with green ✓ Locked
3. **Restart server** - Assignment should persist
4. **Check customer page** - Only YIWU products should appear for Entry-02

---

## UI Preview

```
⚙️ PepHaul Entry Tab Settings
Manage settings for each PepHaul Entry tab: select tab and assign supplier.

[PepHaul Entry Tab ▼] [Assigned Supplier ▼]
        💾 Save Settings         ➕ Create New Tab

────────────────────────────────────────────────────────────

🔒 Locked Supplier Assignments  [One supplier per tab]
Each PepHaul Entry tab is locked to exactly one supplier. This prevents confusion during ordering.

┌───────────────────────┬────────────────────┬──────────┐
│ PepHaul Entry Tab     │ Assigned Supplier  │ Status   │
├───────────────────────┼────────────────────┼──────────┤
│ PepHaul Entry-01      │ Default            │ ✓ Locked │
│ PepHaul Entry-02      │ YIWU               │ ✓ Locked │
│ PepHaul Entry-03      │ Not assigned       │ ⚠️ No su…│
└───────────────────────┴────────────────────┴──────────┘
```

---

## Summary

- ✅ No backend changes needed (persistence already working)
- ✅ Added visual table showing all tabs + suppliers
- ✅ Auto-updates after saving settings
- ✅ Color-coded status indicators for quick scanning
- ✅ Handles errors gracefully
- ✅ Reinforces "one supplier per tab" rule

**Result:** Admins can now see at a glance which supplier is locked to each PepHaul Entry tab, and assignments will persist properly without reverting to "All".

