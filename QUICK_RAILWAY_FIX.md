# Quick Fix: 500 Error on Order Submission

## The Problem
You're getting a 500 error because Railway doesn't have your Google Sheets credentials.

## The Fix (5 minutes)

### Step 1: Get Your Google Credentials
- You should have a `credentials.json` file (from Google Cloud Console)
- If you don't have it, you need to create a service account in Google Cloud Console

### Step 2: Add to Railway
1. Go to https://railway.app
2. Open your project
3. Click on your **service** (web service)
4. Click **"Variables"** tab
5. Click **"+ New Variable"**

### Step 3: Add These Variables

**Variable 1: GOOGLE_CREDENTIALS_JSON**
- **Key:** `GOOGLE_CREDENTIALS_JSON`
- **Value:** Paste your ENTIRE `credentials.json` file content here
  - Open `credentials.json` in a text editor
  - Copy everything (all the JSON)
  - Paste it into Railway (Railway supports multi-line JSON)

**Variable 2: FLASK_DEBUG**
- **Key:** `FLASK_DEBUG`
- **Value:** `false`

**Variable 3: PORT**
- **Key:** `PORT`
- **Value:** `5000`

**Variable 4: ADMIN_FEE_PHP**
- **Key:** `ADMIN_FEE_PHP`
- **Value:** `300`

**Variable 5: FALLBACK_EXCHANGE_RATE**
- **Key:** `FALLBACK_EXCHANGE_RATE`
- **Value:** `59.20`

**Variable 6: GOOGLE_SHEETS_ID**
- **Key:** `GOOGLE_SHEETS_ID`
- **Value:** `18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s`

**Variable 7: SECRET_KEY** (for Flask sessions)
- **Key:** `SECRET_KEY`
- **Value:** Generate one: Run `python -c "import secrets; print(secrets.token_hex(32))"` and paste result

**Variable 8: ADMIN_PASSWORD** (optional but recommended)
- **Key:** `ADMIN_PASSWORD`
- **Value:** Your admin password

### Step 4: Save and Wait
- Click **Save** or **Deploy**
- Railway will automatically redeploy
- Wait 1-2 minutes for deployment to complete

### Step 5: Verify
1. Check Railway logs (Deployments → View Logs)
2. Look for: `✅ Google services initialized`
3. If you see `❌ No Google credentials found`, go back and check `GOOGLE_CREDENTIALS_JSON`

### Step 6: Test
1. Go to your Railway app URL
2. Try submitting an order
3. Should work now! ✅

## Still Not Working?

**Check Railway Logs for:**
- `GOOGLE_CREDENTIALS_JSON exists: True` ← Should say True
- `✅ Google services initialized` ← Should see this
- `❌` ← Any red X means error

**Common Issues:**
1. **"No Google credentials found"** → `GOOGLE_CREDENTIALS_JSON` not set or empty
2. **"JSON parse error"** → Invalid JSON - paste it exactly as it appears in file
3. **"Permission denied"** → Service account needs access to Google Sheet:
   - Open Google Sheet
   - Click Share
   - Add service account email (from credentials.json)
   - Give Editor permissions

## Need More Help?
See `RAILWAY_ENV_CHECKLIST.md` for detailed troubleshooting.

