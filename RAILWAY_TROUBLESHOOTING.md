# Railway Troubleshooting Guide

## Issue: 500 Error on Order Submission + Orders Not Loading

### Quick Diagnosis Steps

1. **Check Railway Logs:**
   - Go to Railway Dashboard → Your Service → Deployments → Latest → View Logs
   - Look for these messages:
     - `✅ Google services initialized` = Good
     - `❌ No Google credentials found` = Bad - credentials not set
     - `JSON parse error` = Bad - invalid JSON format
     - `Permission denied` = Bad - service account needs access

2. **Check Environment Variables:**
   - Railway Dashboard → Your Service → Variables tab
   - Verify `GOOGLE_CREDENTIALS_JSON` is set (should be long JSON text)
   - Verify `GOOGLE_SHEETS_ID=18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s`

3. **Test Google Sheets Access:**
   - Run diagnostic component: `python components/test_google_sheets_connection.py`
   - Check output: `data/output/connection_test_report.txt`

### Common Issues & Fixes

#### Issue 1: "Google Sheets client not initialized"
**Cause:** `GOOGLE_CREDENTIALS_JSON` not set or invalid in Railway

**Fix:**
1. Go to Railway Dashboard → Variables
2. Check `GOOGLE_CREDENTIALS_JSON` exists
3. If missing/invalid:
   - Open your `credentials.json` file
   - Copy ENTIRE content
   - Paste into Railway (Railway supports multi-line JSON)
   - Save and wait for redeploy

#### Issue 2: "Permission denied" or "Access denied"
**Cause:** Service account doesn't have access to Google Sheet

**Fix:**
1. Open Google Sheet: https://docs.google.com/spreadsheets/d/18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s
2. Click **Share** button
3. Get service account email from `credentials.json` (looks like `xxx@xxx.iam.gserviceaccount.com`)
4. Add service account email with **Editor** permissions
5. Save

#### Issue 3: "Worksheet 'PepHaul Entry' not found"
**Cause:** Worksheet name mismatch or doesn't exist

**Fix:**
1. Open Google Sheet
2. Check if tab named "PepHaul Entry" exists (exact spelling, case-sensitive)
3. If not, rename tab to "PepHaul Entry" exactly
4. Or create new tab with that name

#### Issue 4: Orders not loading (empty list)
**Cause:** 
- Cache issue (orders cached as empty)
- Worksheet is actually empty
- Reading wrong worksheet

**Fix:**
1. Check Railway logs for: `📋 Total rows in sheet`
2. If 0 or 1, worksheet is empty
3. If > 1 but orders not showing, clear cache:
   - Visit: `https://your-app.up.railway.app/api/admin/debug/orders` (admin only)
   - Or restart Railway service

### Diagnostic Commands

**Test connection locally:**
```bash
python components/test_google_sheets_connection.py
```

**Check Railway logs:**
- Railway Dashboard → Deployments → View Logs
- Look for print statements from `init_google_services()` and `_fetch_orders_from_sheets()`

### What to Look For in Railway Logs

**✅ Good signs:**
```
GOOGLE_CREDENTIALS_JSON exists: True
Credentials parsed successfully. Service account: xxx@xxx.iam.gserviceaccount.com
✅ Google services initialized from environment variable
📋 Available worksheets in sheet: ['PepHaul Entry', 'Price List', ...]
📋 Total rows in sheet: 150
```

**❌ Bad signs:**
```
❌ No Google credentials found
JSON parse error: ...
Permission denied
Worksheet 'PepHaul Entry' not found
```

### Next Steps

1. Check Railway logs first (most important!)
2. Verify environment variables are set correctly
3. Verify service account has access to Google Sheet
4. Run diagnostic component to test connection
5. Share Railway logs if still having issues

