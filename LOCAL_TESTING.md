# Local Testing Guide

This guide helps you test the application locally before pushing to GitHub and deploying to Render.

## Quick Start (Easiest Method)

**Use the automated test script:**
```bash
python3 test_local.py
```

This script will:
- ✅ Check your setup
- ✅ Validate syntax
- ✅ Start the Flask app automatically

## Manual Setup

**1. Create Virtual Environment (Recommended)**
```bash
# Mac/Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

**2. Install Dependencies**
```bash
pip install -r requirements.txt
```

**3. Set Up Environment Variables**
Create a `.env` file in the project root with your configuration:
```bash
# Required
GOOGLE_SHEETS_ID=your_sheets_id
ADMIN_PASSWORD=your_admin_password

# Optional (with defaults)
ADMIN_FEE_PHP=300
FALLBACK_EXCHANGE_RATE=59.20
FLASK_DEBUG=true
PORT=5000

# Telegram (optional)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ADMIN_CHAT_ID=your_chat_id
TELEGRAM_BOT_USERNAME=pephaul_bot

# Google Drive (optional)
PAYMENT_DRIVE_FOLDER_ID=your_folder_id
```

**4. Run the Application**
```bash
python app.py
# OR use the test script:
python3 test_local.py
```

The app will start at: **http://localhost:5000**

## Testing Checklist

Before pushing to GitHub/Render, test these features:

### ✅ Basic Functionality
- [ ] Homepage loads correctly
- [ ] Product dropdown shows PHP conversion
- [ ] Product cards show PHP prices
- [ ] Can search and select products
- [ ] Can add items to cart
- [ ] Cart shows correct totals (USD + PHP + Admin Fee)

### ✅ Order Management
- [ ] Can submit new order
- [ ] Order appears in admin panel
- [ ] Can view order details
- [ ] Can cancel order (deletes rows)
- [ ] Can add items to existing order
- [ ] Totals recalculate correctly

### ✅ Admin Panel
- [ ] Can login to admin panel
- [ ] Can view all orders
- [ ] Can filter/search orders
- [ ] Can confirm payments
- [ ] Can lock/unlock orders
- [ ] Can cancel orders
- [ ] Product management works

### ✅ Syntax Validation
- [ ] Run: `python3 pre_update_validation.py`
- [ ] All files pass validation
- [ ] No syntax errors

## Common Issues

**Port Already in Use:**
```bash
# Find and kill process using port 5000
lsof -ti:5000 | xargs kill -9

# Or use a different port
PORT=5001 python app.py
```

**Missing Dependencies:**
```bash
pip install -r requirements.txt
```

**Google Sheets Authentication:**
- Make sure you have `credentials.json` or OAuth set up
- Check that `GOOGLE_SHEETS_ID` is correct in `.env`

**Telegram Bot Not Working:**
- Telegram features are optional - app works without them
- Check `TELEGRAM_BOT_TOKEN` is set if you want Telegram features

## Testing Workflow

1. **Make Changes** → Edit code
2. **Validate Syntax** → `python3 pre_update_validation.py`
3. **Test Locally** → `python3 test_local.py` or `python app.py`
4. **Test Features** → Use checklist above
5. **Fix Issues** → Debug and fix locally
6. **Commit** → `git add .` and `git commit`
7. **Push** → `git push` (deploys to Render automatically)

## Development Tips

- Use `FLASK_DEBUG=true` in `.env` for auto-reload on code changes
- Check terminal output for errors
- Use browser developer tools (F12) to check console errors
- Test with different browsers if possible
- The test script (`test_local.py`) validates everything before starting

## Stopping the Server

Press `Ctrl+C` in the terminal to stop the Flask server.

## URLs to Test

- **Homepage:** http://localhost:5000
- **Admin Panel:** http://localhost:5000/admin
- **API Endpoints:** http://localhost:5000/api/products, etc.
