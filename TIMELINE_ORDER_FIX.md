# Timeline Order and Reordering Feature

## 🎯 Issues Fixed

### 1. **Timeline entries not appearing in proper sequence**
- Previously, timeline entries were sorted by date/time which could be inconsistent
- Now uses a dedicated "Sequence" field for explicit ordering

### 2. **No ability to reorder timeline entries**
- Added "Up" and "Down" buttons to move entries in the timeline
- Admin can now arrange timeline entries in any order regardless of date

### 3. **Timeline visibility in customer panel**
- Ensured "View Different PepHaul Entry Orders" section persists across all views
- Timeline view shows this tab switcher so customers can view different PepHaul Entry timelines

## ✅ Changes Made

### **Backend (app.py)**

#### 1. **Added Sequence Field to Timeline Schema**
- Updated all Timeline sheet creation/migration code to include "Sequence" column (Column F)
- Modified `_fetch_timeline_entries()` to read and parse sequence values
- Modified `_fetch_all_timeline_entries()` to include sequence in all entries
- Updated `add_timeline_entry()` to auto-assign next sequence number when creating new entries

#### 2. **Added Reorder Functionality**
- Created `reorder_timeline_entry(entry_id, direction, tab_name)` function
  - Moves entries up or down within their tab
  - Swaps sequence numbers between adjacent entries
  - Handles edge cases (can't move up from top, can't move down from bottom)
  - Only affects entries within the same PepHaul Entry tab

#### 3. **Added Reorder API Endpoint**
- New endpoint: `POST /api/admin/timeline/<entry_id>/reorder`
- Parameters: `direction` ("up" or "down"), `tab_name`
- Requires admin authentication
- Returns success/error status

### **Admin Panel (templates/admin.html)**

#### 1. **Updated Timeline Sorting**
- Changed from date/time sorting to sequence-based sorting
- Entries now display in the order specified by their sequence number

```javascript
// Old: Sort by date
const sortedEntries = data.entries.sort((a, b) => {
    const dateA = parseTimelineDate(a.date, a.time);
    const dateB = parseTimelineDate(b.date, b.time);
    return dateA - dateB;
});

// New: Sort by sequence
const sortedEntries = data.entries.sort((a, b) => {
    const seqA = typeof a.sequence === 'number' ? a.sequence : 999999;
    const seqB = typeof b.sequence === 'number' ? b.sequence : 999999;
    return seqA - seqB;
});
```

#### 2. **Added Move Up/Down Buttons**
- Added "⬆️ Up" and "⬇️ Down" buttons next to Edit and Delete buttons
- Buttons styled in blue (#3b82f6) to distinguish from Edit (yellow) and Delete (red)

#### 3. **Added JavaScript Handler**
- Created `moveTimelineEntry(entryId, direction)` function
- Calls the reorder API endpoint
- Shows success/error toast notification
- Reloads timeline to show new order

### **Customer Panel (templates/index.html)**

#### 1. **Updated All Timeline Sorting**
Updated sorting in three places:
- `renderTimelineHtml()` - Main timeline rendering function
- `loadTimeline()` - Embedded timeline (when form is locked)
- All timeline views now use sequence-based sorting

#### 2. **Verified Tab Switcher Persistence**
- "View Different PepHaul Entry Orders" section (customer-tab-switcher) is NOT hidden in timeline-only mode
- Remains visible across all views when there are locked tabs
- Customers can switch between different PepHaul Entry timelines

## 📊 Database Schema Change

### Timeline Sheet (Google Sheets)

**Before:**
```
| ID | PepHaul Entry ID | Date | Time | Details of Transaction |
```

**After:**
```
| ID | PepHaul Entry ID | Date | Time | Details of Transaction | Sequence |
```

**Migration:**
- Existing Timeline sheets automatically get the Sequence column added
- Existing entries get sequence numbers based on their current row order
- New entries get sequence = max(existing sequences) + 1

## 🔄 How Reordering Works

1. **Admin clicks "⬆️ Up" or "⬇️ Down"** button on a timeline entry
2. **API request** sent to `/api/admin/timeline/<entry_id>/reorder`
3. **Server logic:**
   - Fetches all entries for the current tab
   - Sorts by current sequence
   - Finds the entry to move
   - Checks if move is valid (not at top/bottom)
   - Swaps sequence numbers with adjacent entry
   - Updates Google Sheet
   - Clears cache
4. **UI updates** - timeline reloads showing new order
5. **All views updated** - customer panel, embedded timeline, and order timeline view all reflect new sequence

## 🎨 UI Changes

### Admin Panel Timeline Entry
```
┌─────────────────────────────────────────────────────────┐
│ 🕒 2026-01-02 • 5:40 PM                                │
│ PepHaul Entry-02 Form Locked for ordering              │
│                                                         │
│ [⬆️ Up] [⬇️ Down] [✏️ Edit] [🗑️ Delete]                │
└─────────────────────────────────────────────────────────┘
```

### Customer Panel
- Timeline entries always sorted by sequence (admin-defined order)
- Tab switcher persists in all views
- Customers see consistent ordering across all devices

## 🔐 Security & Permissions

- **Reordering:** Admin-only (requires `session['is_admin']`)
- **Viewing:** Public (customers can view timelines)
- **Tab-specific:** Entries can only be reordered within their own PepHaul Entry tab

## 🧪 Testing Checklist

- [x] Sequence field added to new Timeline sheets
- [x] Existing Timeline sheets get Sequence column added
- [x] New timeline entries get proper sequence numbers
- [x] Timeline sorting uses sequence instead of date
- [x] Move Up button works (swaps with entry above)
- [x] Move Down button works (swaps with entry below)
- [x] Edge cases handled (can't move beyond boundaries)
- [x] Admin panel timeline shows correct order
- [x] Customer panel timeline shows correct order
- [x] Embedded timeline shows correct order
- [x] Timeline view shows correct order
- [x] Tab switcher persists in timeline view
- [x] No linter errors introduced
- [x] All views respect sequence ordering

## 📝 Notes

- Timeline entries can now be in any order (not restricted by date/time)
- Admins control the exact order customers see
- Useful for organizing timeline by importance or logical flow rather than chronological order
- Date/time fields still preserved for reference but don't control display order

