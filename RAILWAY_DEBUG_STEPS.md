# Railway Debug Steps - 500 Error Fix

## The Problem

You're getting a 500 error when submitting orders, and orders aren't loading. This usually means Google Sheets isn't connecting properly on Railway.

## Step-by-Step Fix

### Step 1: Check Railway Logs (Most Important!)

1. Go to Railway Dashboard: https://railway.app
2. Click on your service
3. Click **"Deployments"** tab
4. Click on the **latest deployment**
5. Click **"View Logs"**

**Look for these messages:**

**✅ Good (credentials working):**
```
GOOGLE_CREDENTIALS_JSON exists: True
Credentials parsed successfully. Service account: xxx@xxx.iam.gserviceaccount.com
✅ Google services initialized from environment variable
```

**❌ Bad (credentials not working):**
```
❌ No Google credentials found
JSON parse error: ...
GOOGLE_CREDENTIALS_JSON exists: False
```

### Step 2: Verify Environment Variables in Railway

1. Railway Dashboard → Your Service → **"Variables"** tab
2. Check these variables exist:

**Required:**
- `GOOGLE_CREDENTIALS_JSON` - Should be LONG (hundreds/thousands of characters)
- `GOOGLE_SHEETS_ID` - Should be `18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s`
- `FLASK_DEBUG=false`
- `PORT=5000`

**If `GOOGLE_CREDENTIALS_JSON` is missing or short:**
1. Open your `credentials.json` file
2. Copy the ENTIRE file content (all of it)
3. In Railway Variables, add/edit `GOOGLE_CREDENTIALS_JSON`
4. Paste the entire JSON (Railway handles multi-line JSON)
5. Save - Railway will auto-redeploy

### Step 3: Verify Service Account Has Access

1. Open your Google Sheet: https://docs.google.com/spreadsheets/d/18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s
2. Click **"Share"** button (top right)
3. Get your service account email:
   - Open `credentials.json` file
   - Find `"client_email"` field
   - Copy that email (looks like `xxx@xxx.iam.gserviceaccount.com`)
4. In Google Sheets Share dialog:
   - Paste the service account email
   - Set permission to **"Editor"**
   - Click **"Send"** or **"Share"**

### Step 4: Verify Worksheet Name

1. Open your Google Sheet
2. Check if there's a tab named exactly: **"PepHaul Entry"** (case-sensitive, exact spelling)
3. If not:
   - Rename the tab to "PepHaul Entry" exactly
   - Or create a new tab with that name

### Step 5: Test After Fixes

After making changes:

1. **Railway will auto-redeploy** (watch Deployments tab)
2. Wait for deployment to complete (green checkmark)
3. Check logs again - should see `✅ Google services initialized`
4. Test your app:
   - Visit your Railway URL
   - Try submitting an order
   - Should work now!

## Quick Test Commands

If you have Railway CLI or SSH access:

```bash
# Test connection
python components/test_google_sheets_connection.py

# Fetch orders
python workflow.py
```

## Still Not Working?

Share these from Railway logs:
1. Any lines with `❌` or `ERROR`
2. Lines about `GOOGLE_CREDENTIALS_JSON`
3. Lines about `Google services initialized`
4. Any error messages

This will help identify the exact issue!

