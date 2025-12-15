# Fix Railway Credentials - Step by Step

## The Problem

Railway logs show:
```
GOOGLE_CREDENTIALS_JSON exists: False
GOOGLE_CREDENTIALS_JSON length: 0
❌ No Google credentials found
```

This means Railway can't find your Google credentials, so the app can't connect to Google Sheets.

## The Fix (5 Minutes)

### Step 1: Get Your Credentials File

1. Find your `credentials.json` file (from Google Cloud Console)
2. Open it in a text editor (like VS Code, TextEdit, or Notepad)
3. You'll see JSON that looks like:
   ```json
   {
     "type": "service_account",
     "project_id": "...",
     "private_key_id": "...",
     "private_key": "...",
     "client_email": "...",
     ...
   }
   ```

### Step 2: Copy the ENTIRE JSON

1. Select ALL the text in the file (Cmd+A or Ctrl+A)
2. Copy it (Cmd+C or Ctrl+C)
3. Make sure you got everything - it should be hundreds or thousands of characters

### Step 3: Add to Railway

1. Go to Railway Dashboard: https://railway.app
2. Click on your service: **pephaul-order-form**
3. Click **"Variables"** tab (top menu)
4. Look for `GOOGLE_CREDENTIALS_JSON` in the list

**If it doesn't exist:**
- Click **"+ New Variable"** button
- **Key:** `GOOGLE_CREDENTIALS_JSON`
- **Value:** Paste your ENTIRE JSON (the whole thing you copied)
- Click **"Add"**

**If it exists but is empty/wrong:**
- Click on `GOOGLE_CREDENTIALS_JSON` to edit it
- Delete the old value
- Paste your ENTIRE JSON
- Click **"Save"**

### Step 4: Important Notes

**Railway supports multi-line JSON** - paste it exactly as it appears in your file:
- Don't add quotes around it
- Don't escape anything
- Don't put it on one line
- Just paste it exactly as it appears in `credentials.json`

**The value should be LONG** - if it's only a few characters, you didn't copy everything.

### Step 5: Wait for Redeploy

1. After saving, Railway will automatically redeploy
2. Go to **Deployments** tab
3. Wait for new deployment to complete (green checkmark)
4. Click on it → **View Logs**
5. Look for: `✅ Google services initialized`

### Step 6: Verify It Worked

**Good signs in logs:**
```
GOOGLE_CREDENTIALS_JSON exists: True
GOOGLE_CREDENTIALS_JSON length: [large number]
Credentials parsed successfully. Service account: xxx@xxx.iam.gserviceaccount.com
✅ Google services initialized from environment variable
```

**Bad signs (if you still see these):**
```
GOOGLE_CREDENTIALS_JSON exists: False
JSON parse error
```

If you see "JSON parse error", the JSON format is wrong - make sure you pasted it exactly as it appears in the file.

## Quick Checklist

- [ ] Opened `credentials.json` file
- [ ] Copied ENTIRE content (all of it)
- [ ] Went to Railway → Variables tab
- [ ] Added/edited `GOOGLE_CREDENTIALS_JSON`
- [ ] Pasted entire JSON (not just part of it)
- [ ] Saved in Railway
- [ ] Waited for redeploy
- [ ] Checked logs for `✅ Google services initialized`

## Still Not Working?

**Check these:**

1. **Did you copy the entire JSON?** - Should be very long (hundreds/thousands of characters)
2. **Is the JSON valid?** - Should start with `{` and end with `}`
3. **Did Railway save it?** - Check Variables tab, click on `GOOGLE_CREDENTIALS_JSON` to see if value is there
4. **Did Railway redeploy?** - Check Deployments tab for new deployment

Once you see `✅ Google services initialized` in the logs, your app will work!

