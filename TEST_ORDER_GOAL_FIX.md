# Testing Order Goal Fix - Local Testing Guide

This guide helps you test the order goal fix locally before pushing to production.

## Quick Start

**Easiest way to test:**
```bash
python3 test_local.py
```

This will:
- ✅ Check your setup
- ✅ Validate syntax
- ✅ Start Flask app automatically

Then open: **http://localhost:5000**

## Step-by-Step Testing Process

### 1. Setup (First Time Only)

**Activate virtual environment:**
```bash
# Mac/Linux
source venv/bin/activate

# Windows
venv\Scripts\activate
```

**Install dependencies (if needed):**
```bash
pip install -r requirements.txt
```

**Verify .env file exists:**
- Make sure `.env` has `GOOGLE_SHEETS_ID` and `ADMIN_PASSWORD`
- The app will read order goal from Google Sheets automatically

### 2. Start the App

**Option A: Use test script (recommended)**
```bash
python3 test_local.py
```

**Option B: Run directly**
```bash
python app.py
```

The app will start at: **http://localhost:5000**

### 3. Test Order Goal Changes

#### Test 1: Verify Order Goal Loads from Sheets
1. **Open homepage:** http://localhost:5000
2. **Check Statistics section** - Should show actual goal from Google Sheets (not hardcoded 1000)
3. **Verify progress bars** - Should calculate against actual goal

#### Test 2: Update Goal in Admin Panel
1. **Open admin panel:** http://localhost:5000/admin
2. **Login** with admin password
3. **Find "Order Goal Settings"** section
4. **Change goal** to a different value (e.g., 2000)
5. **Click "Save Goal"**
6. **Refresh homepage** - Statistics should show new goal immediately

#### Test 3: Verify Cache Clearing
1. **Set goal to 2000** in admin panel
2. **Refresh homepage** - Should show 2000
3. **Set goal to 3000** in admin panel
4. **Refresh homepage** - Should show 3000 (not cached 2000)
5. **Check progress calculations** - Should use 3000 as denominator

#### Test 4: Test Direct Google Sheets Update
1. **Open Google Sheets** - Settings tab
2. **Find "Order Goal" row**
3. **Change Value** to 5000
4. **Refresh homepage** - Should show 5000 (may take up to 10 minutes due to cache, or clear cache by updating via admin panel)

### 4. What to Look For

**✅ Success Indicators:**
- Statistics section shows actual goal from sheets (not 1000)
- Progress bars calculate correctly against actual goal
- Admin panel loads current goal value (not default 1000)
- Changing goal in admin updates Statistics immediately
- No errors in browser console (F12 → Console tab)
- No errors in terminal where Flask is running

**❌ Issues to Watch For:**
- Statistics still showing 1000 after updating goal
- Admin panel input field shows 1000 instead of actual value
- Progress calculations using wrong denominator
- JavaScript errors in browser console
- Python errors in terminal

### 5. Debugging Tips

**Check browser console:**
- Press F12 → Console tab
- Look for JavaScript errors
- Check network tab for API calls to `/api/admin/order-goal`

**Check Flask terminal:**
- Look for Python errors
- Check for "Error getting order goal" messages
- Verify Google Sheets connection is working

**Check cache:**
- If goal doesn't update, cache might be stale (10 minute duration)
- Update goal via admin panel to force cache clear
- Or wait 10 minutes for cache to expire

**Verify Google Sheets:**
- Open Settings sheet
- Check "Order Goal" row exists
- Verify "Value" column has correct number
- Check "Updated" timestamp is recent

### 6. Pre-Push Checklist

Before pushing to GitHub/production:

- [ ] ✅ App starts without errors
- [ ] ✅ Homepage loads correctly
- [ ] ✅ Statistics section shows actual goal (not 1000)
- [ ] ✅ Admin panel loads current goal value
- [ ] ✅ Can update goal in admin panel
- [ ] ✅ Goal update reflects immediately on homepage
- [ ] ✅ Progress bars calculate correctly
- [ ] ✅ No JavaScript errors in console
- [ ] ✅ No Python errors in terminal
- [ ] ✅ Syntax validation passes: `python3 pre_update_validation.py`

### 7. Common Issues & Fixes

**Issue: Still showing 1000**
- **Fix:** Clear browser cache (Ctrl+Shift+R or Cmd+Shift+R)
- **Fix:** Check Google Sheets has correct value
- **Fix:** Update goal via admin panel to force cache clear

**Issue: Admin panel shows 1000**
- **Fix:** Check `/api/admin/order-goal` endpoint returns correct value
- **Fix:** Check browser console for API errors
- **Fix:** Verify Google Sheets connection

**Issue: Goal doesn't update after saving**
- **Fix:** Check terminal for errors
- **Fix:** Verify Google Sheets write permissions
- **Fix:** Check network tab for API response

**Issue: Port already in use**
```bash
# Find and kill process
lsof -ti:5000 | xargs kill -9

# Or use different port
PORT=5001 python app.py
```

### 8. Testing Workflow

**Recommended order:**
1. **Start app:** `python3 test_local.py`
2. **Test homepage:** Verify Statistics shows correct goal
3. **Test admin panel:** Login → Update goal → Verify homepage updates
4. **Test edge cases:** Empty goal, very large goal, negative goal (should be blocked)
5. **Check logs:** Verify no errors in terminal
6. **Validate syntax:** `python3 pre_update_validation.py`
7. **Commit changes:** `git add .` and `git commit -m "Fix order goal static 1000 value"`
8. **Push to GitHub:** `git push` (deploys to production)

### 9. URLs to Test

- **Homepage:** http://localhost:5000
- **Admin Panel:** http://localhost:5000/admin
- **Order Goal API:** http://localhost:5000/api/admin/order-goal (GET)
- **Update Goal API:** http://localhost:5000/api/admin/order-goal (POST)

### 10. Stopping the Server

Press `Ctrl+C` in the terminal to stop the Flask server.

---

## Summary

**Quick test command:**
```bash
python3 test_local.py
```

**What changed:**
- Removed hardcoded 1000 fallbacks in `app.py`
- Removed hardcoded 1000 in admin panel HTML/JavaScript
- Cache now clears immediately when goal is updated
- Goal now properly reads from Google Sheets

**What to verify:**
- Statistics shows actual goal from sheets
- Admin panel loads and saves goal correctly
- Changes reflect immediately (no stale cache)

