# Railway Deployment Steps - Complete Guide

## ✅ Pre-Deployment Checklist

Your code is ready! Here's what you need to do in Railway:

### 1. Verify Railway Project Setup
- ✅ Repository connected to Railway
- ✅ Service created
- ✅ Auto-deploy enabled

### 2. Set Environment Variables in Railway

Go to Railway Dashboard → Your Service → **Variables** tab

**Required Variables (copy these exactly):**

```
FLASK_DEBUG=false
PORT=5000
ADMIN_FEE_PHP=300
FALLBACK_EXCHANGE_RATE=59.20
GOOGLE_SHEETS_ID=18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s
```

**Critical - Google Credentials:**
```
GOOGLE_CREDENTIALS_JSON=<paste your entire credentials.json content here>
```

**Security Variables:**
```
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
ADMIN_PASSWORD=<your secure admin password>
```

**Optional - Telegram (if using):**
```
TELEGRAM_BOT_TOKEN=<your bot token>
TELEGRAM_ADMIN_CHAT_ID=<your chat ID>
TELEGRAM_ADMIN_CHAT_IDS=<comma-separated chat IDs>
TELEGRAM_BOT_USERNAME=pephaul_bot
```

### 3. How to Add Variables in Railway

1. Click **"+ New Variable"** button
2. Enter **Key** (e.g., `GOOGLE_SHEETS_ID`)
3. Enter **Value** (e.g., `18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s`)
4. Click **Add**
5. Repeat for each variable

**For GOOGLE_CREDENTIALS_JSON:**
- Open your `credentials.json` file
- Copy the ENTIRE JSON content
- Paste it into Railway as the value
- Railway supports multi-line JSON - paste it exactly as it appears

### 4. Verify Deployment

After adding variables, Railway will automatically redeploy:

1. Go to **Deployments** tab
2. Wait for deployment to complete (green checkmark)
3. Click on latest deployment → **View Logs**
4. Look for these success messages:

**✅ Good signs:**
```
✅ Google services initialized from environment variable
✅ Found 'PepHaul Entry' worksheet
```

**❌ If you see errors:**
- `❌ No Google credentials found` → `GOOGLE_CREDENTIALS_JSON` not set correctly
- `JSON parse error` → Invalid JSON format in credentials
- `Permission denied` → Service account needs access to Google Sheet

### 5. Test Your App

1. Get your Railway URL: `https://your-app.up.railway.app`
2. Visit the URL - should see your order form
3. Try submitting a test order
4. Check Railway logs for any errors

### 6. Test Component System (Optional)

If you want to run the component system on Railway, you can:

1. SSH into Railway (if available) or
2. Add a scheduled task, or
3. Run components locally (they'll use Railway's environment variables if configured)

## Troubleshooting

### App won't start
- Check Railway logs for errors
- Verify all environment variables are set
- Check `requirements.txt` includes all dependencies ✅

### 500 Error on order submission
- Verify `GOOGLE_CREDENTIALS_JSON` is set correctly
- Check service account has access to Google Sheet
- Look at Railway logs for specific error messages

### Component system not working
- Components work locally and on Railway
- Make sure `GOOGLE_CREDENTIALS_JSON` is set in Railway
- Check logs/audit_log.txt for detailed errors

## What's Deployed

✅ Flask web app (`app.py`)
✅ Component system (`components/`, `workflow.py`)
✅ Data connector (`data_sources.py`)
✅ All dependencies (`requirements.txt`)

## Next Steps After Deployment

1. ✅ Test order submission
2. ✅ Verify orders appear in Google Sheets
3. ✅ Test admin panel
4. ✅ Run component system: `python workflow.py` (if you have Railway CLI or SSH access)

Your app is ready for Railway! 🚀

