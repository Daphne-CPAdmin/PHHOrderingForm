# Railway Environment Variables Checklist

## ⚠️ CRITICAL: Required for Order Submission

Your app is getting a 500 error because these environment variables are missing in Railway.

## Step-by-Step Setup in Railway

### 1. Go to Railway Dashboard
- Open your project: https://railway.app
- Click on your service (the web service)
- Click **"Variables"** tab

### 2. Add These Environment Variables

**Copy each variable name and value below, then paste into Railway:**

#### Required Variables (App won't work without these):

```
FLASK_DEBUG=false
PORT=5000
ADMIN_FEE_PHP=300
FALLBACK_EXCHANGE_RATE=59.20
GOOGLE_SHEETS_ID=18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s
```

#### Critical: Google Sheets Credentials (THIS IS WHY YOU'RE GETTING 500 ERROR!)

```
GOOGLE_CREDENTIALS_JSON=<paste your entire credentials.json here>
```

**How to get this:**
1. You should have a `credentials.json` file from Google Cloud Console
2. Open that file in a text editor
3. Copy the ENTIRE JSON content (all of it, including { and })
4. Paste it into Railway as the value for `GOOGLE_CREDENTIALS_JSON`

**Important:** 
- Railway supports multi-line JSON - paste it exactly as it appears
- Don't add quotes around it
- Don't escape anything - paste it raw

#### Security Variables (Generate new ones for production):

```
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
ADMIN_PASSWORD=<your secure admin password>
```

#### Optional: Telegram Notifications (if you use Telegram)

```
TELEGRAM_BOT_TOKEN=<your bot token>
TELEGRAM_ADMIN_CHAT_ID=<your chat ID>
TELEGRAM_ADMIN_CHAT_IDS=<comma-separated chat IDs>
TELEGRAM_BOT_USERNAME=pephaul_bot
```

### 3. After Adding Variables

1. **Save** the variables in Railway
2. Railway will **automatically redeploy** your app
3. Wait for deployment to complete (check Deployments tab)
4. Test order submission again

## How to Verify Variables Are Set

### Check Railway Logs:
1. Go to Railway Dashboard → Your Service → **Deployments** tab
2. Click on latest deployment → **View Logs**
3. Look for these messages on startup:

**✅ Good (credentials found):**
```
GOOGLE_CREDENTIALS_JSON exists: True
Credentials parsed successfully. Service account: your-service-account@...
✅ Google services initialized from environment variable
```

**❌ Bad (credentials missing):**
```
GOOGLE_CREDENTIALS_JSON exists: False
❌ No Google credentials found - set GOOGLE_CREDENTIALS_JSON env variable
```

## Common Issues

### Issue: "500 Error" when submitting order
**Cause:** `GOOGLE_CREDENTIALS_JSON` is missing or invalid
**Fix:** 
1. Check Railway Variables tab - is `GOOGLE_CREDENTIALS_JSON` set?
2. Check logs - does it say "No Google credentials found"?
3. Verify JSON is valid - paste it into https://jsonlint.com to check

### Issue: "Invalid JSON" error in logs
**Cause:** JSON is malformed (extra quotes, escaped characters)
**Fix:** 
- Paste JSON exactly as it appears in your `credentials.json` file
- Don't add quotes around it
- Don't escape anything

### Issue: "Permission denied" when saving orders
**Cause:** Service account doesn't have access to Google Sheet
**Fix:**
1. Open your Google Sheet
2. Click **Share** button
3. Add the service account email (from credentials.json, looks like `xxx@xxx.iam.gserviceaccount.com`)
4. Give it **Editor** permissions

## Quick Test After Setup

1. Go to your Railway app URL: `https://your-app.up.railway.app`
2. Try submitting a test order
3. Check Railway logs for any errors
4. Check Google Sheet - order should appear in "PepHaul Entry" tab

## Still Having Issues?

Check Railway logs for:
- `❌` symbols (errors)
- `⚠️` symbols (warnings)
- Look for the exact error message

Common error messages:
- "No Google credentials found" → `GOOGLE_CREDENTIALS_JSON` not set
- "JSON parse error" → Invalid JSON format
- "Permission denied" → Service account needs access to sheet
- "Sheet not found" → `GOOGLE_SHEETS_ID` is wrong

