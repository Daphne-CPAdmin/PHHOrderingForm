# Railway Deployment Guide

## Why Railway?

✅ **No sleeping** - Free tier stays awake (unlike Render free tier)
✅ **$5/month free credit** - Usually enough for small Flask apps
✅ **Easy GitHub integration** - Auto-deploy on push
✅ **Similar to Render** - Easy migration

## Migration Steps

### 1. Create Railway Account
- Go to https://railway.app
- Sign up with GitHub (recommended for easy deployment)

### 2. Create New Project
- Click "New Project"
- Select "Deploy from GitHub repo"
- Choose your `PHHOrderingForm` repository

### 3. Configure Environment Variables

Railway will auto-detect your app, but you need to set environment variables:

**In Railway Dashboard → Your Service → Variables tab, add:**

```
# Python Version (optional - Railway auto-detects)
PYTHON_VERSION=3.11.6

# Flask Settings
FLASK_DEBUG=false
PORT=5000

# App Configuration
ADMIN_FEE_PHP=300
FALLBACK_EXCHANGE_RATE=59.20
GOOGLE_SHEETS_ID=18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s

# Security (IMPORTANT - set these!)
SECRET_KEY=<generate a random secret key>
ADMIN_PASSWORD=<your secure admin password>

# Google Sheets Credentials (paste entire JSON here)
GOOGLE_CREDENTIALS_JSON=<paste your entire credentials.json content>

# Telegram (if using)
TELEGRAM_BOT_TOKEN=<your bot token>
TELEGRAM_ADMIN_CHAT_ID=<your chat ID>
TELEGRAM_ADMIN_CHAT_IDS=<comma-separated chat IDs>
TELEGRAM_BOT_USERNAME=pephaul_bot
```

**Important Notes:**
- Railway uses `PORT` environment variable automatically (your app already supports this ✅)
- For `GOOGLE_CREDENTIALS_JSON`: Paste the entire JSON content as a single line (Railway handles multi-line JSON)
- Generate `SECRET_KEY`: Use `python -c "import secrets; print(secrets.token_hex(32))"`

### 4. Deploy

Railway will automatically:
- Detect Python from `requirements.txt`
- Install dependencies
- Run `gunicorn app:app` (from `railway.toml` or auto-detected)
- Assign a public URL

### 5. Get Your URL

- Railway provides a `*.up.railway.app` URL automatically
- You can add a custom domain in Settings → Domains

## Differences from Render

| Feature | Render | Railway |
|---------|--------|---------|
| Free tier sleeping | ✅ Yes (15 min inactivity) | ❌ No (stays awake) |
| Free credit | None | $5/month |
| Auto-deploy | ✅ Yes | ✅ Yes |
| Environment vars | Dashboard | Dashboard |
| Custom domain | ✅ Free | ✅ Free |
| Health checks | ✅ Yes | ✅ Auto |

## Cost Estimate

**Free Tier:**
- $5/month credit
- Usually enough for small Flask apps (~500 hours/month)
- If you exceed: ~$0.01/hour = ~$7/month for 24/7

**Paid Plans:**
- Starter: $5/month + usage
- Developer: $20/month + usage

## Troubleshooting

### ⚠️ 500 Error When Submitting Orders (MOST COMMON ISSUE)

**Symptom:** Order submission fails with 500 error, console shows "Failed to load resource: the server responded with a status of 500"

**Cause:** Missing `GOOGLE_CREDENTIALS_JSON` environment variable

**Fix:**
1. Go to Railway Dashboard → Your Service → **Variables** tab
2. Add `GOOGLE_CREDENTIALS_JSON` variable
3. Paste your entire `credentials.json` file content as the value
4. Save and wait for redeploy
5. Check logs - should see "✅ Google services initialized"

**Verify it's working:**
- Check Railway logs for: `GOOGLE_CREDENTIALS_JSON exists: True`
- If you see `❌ No Google credentials found`, the variable isn't set correctly

### App won't start
- Check logs in Railway Dashboard → Deployments → View Logs
- Verify `gunicorn` is in `requirements.txt` ✅ (it is)
- Check environment variables are set correctly

### Port issues
- Railway sets `PORT` automatically - your app already uses this ✅
- No changes needed

### Google Sheets not working
- Verify `GOOGLE_CREDENTIALS_JSON` is set correctly
- Check JSON is valid (no extra quotes/escapes)
- Railway supports multi-line JSON in environment variables
- **Make sure service account email has access to your Google Sheet:**
  1. Open Google Sheet
  2. Click **Share**
  3. Add service account email (from credentials.json, ends with `@xxx.iam.gserviceaccount.com`)
  4. Give it **Editor** permissions

### Database/Storage
- Railway offers PostgreSQL, MySQL, Redis add-ons
- For file storage, use Railway Volumes or external storage (S3, etc.)

## Rollback Plan

If you want to keep Render as backup:
1. Don't delete Render service yet
2. Test Railway deployment first
3. Update DNS/custom domain to point to Railway
4. Monitor for a few days
5. Then delete Render service

## Next Steps

1. ✅ Railway config files created (`railway.json`, `railway.toml`)
2. Create Railway account and connect GitHub
3. Deploy from GitHub repo
4. Set environment variables
5. Test the deployed app
6. Update custom domain (if you have one)

Your app is already Railway-ready! The `PORT` environment variable and `gunicorn` setup work perfectly with Railway.

