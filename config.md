# PepHaul Order Form - Complete Configuration

## Features

### Customer Features
- **Create New Order** - Add products to cart, submit order
- **View My Orders** - Search and view existing orders
- **Add to Existing Order** - Add items to pending orders
- **Cancel Order** - Cancel orders (if not locked)
- **Upload Payment** - Upload payment screenshot to Google Drive
- **Real-time Inventory** - See vials, kits generated, slots remaining

### Admin Features
- **Product Locking** - Lock products manually or when max kits reached
- **Set Max Kits** - Configure maximum kits per product
- **View Stats** - Total products, locked products, kits generated, vials ordered
- **Order Management** - Lock/unlock orders, view all orders

---

## Fees & Charges

| Fee Type | Amount | Currency | Description |
|----------|--------|----------|-------------|
| Admin Fee | 300 | PHP | Fixed admin fee per order |

## Exchange Rate

- **Source:** Auto-fetched from ExchangeRate-API (free tier)
- **Fallback Rate:** ₱59.20 (if API unavailable)

## Inventory Tracking

- **Total Vials:** Cumulative vials ordered per product
- **Kits Generated:** Total vials ÷ 10 (rounded down)
- **Extra Vials:** Remaining vials after full kits
- **Slots to Next Kit:** 10 - Extra Vials
- **Max Kits:** Configurable per product (default: 100)
- **Auto-Lock:** Products auto-lock when kits_generated >= max_kits

---

## Google Sheets Structure

### PepHaul Entry Tab (Orders)

| Column | Description |
|--------|-------------|
| Order ID | Unique ID (e.g., ORD-20241210123456) |
| Order Date | Submission timestamp |
| Full Name | Customer name |
| Email | Customer email |
| Telegram Username | Telegram handle |
| Product Code | Product code |
| Product Name | Full product name |
| Order Type | Kit or Vial |
| QTY | Quantity |
| Unit Price USD | Unit price in USD |
| Line Total USD | Unit Price × QTY |
| Exchange Rate | USD to PHP rate |
| Line Total PHP | Line total in PHP |
| Admin Fee PHP | ₱300 (first row only) |
| Grand Total PHP | Total in PHP |
| Order Status | Pending, Locked, Cancelled |
| Locked | Yes/No |
| **Payment Status** | Unpaid, Paid |
| **Payment Screenshot** | Google Drive link |
| **Payment Date** | When payment uploaded |
| Notes | Additional notes |

### Product Locks Tab (Admin)

| Column | Description |
|--------|-------------|
| Product Code | Product identifier |
| Max Kits | Maximum kits allowed |
| Is Locked | Yes/No |
| Locked Date | When locked |
| Locked By | Admin who locked |

---

## Admin Access

- **URL:** `/admin`
- **Default Password:** `pephaul2024` (change in `.env`!)
- Set custom password: `ADMIN_PASSWORD=your_secure_password`

---

## Environment Variables

Create a `.env` file:

```
# Google Sheets
GOOGLE_SHEETS_ID=18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s

# For Render deployment (paste entire credentials.json content):
GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}

# App Config
ADMIN_FEE_PHP=300
FALLBACK_EXCHANGE_RATE=59.20
ADMIN_PASSWORD=pephaul2024
SECRET_KEY=your_random_secret_key

# Telegram Notifications
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_ADMIN_CHAT_ID=your_chat_id  # Single admin (backward compatible)
TELEGRAM_ADMIN_CHAT_IDS=@username1,@username2,chat_id3  # Multiple admins (comma-separated)
# Supports both usernames (e.g., @deejay92) and chat IDs
# Usernames are auto-resolved to chat IDs when users message the bot
TELEGRAM_BOT_USERNAME=pephaul_bot

# Flask
FLASK_DEBUG=false
```

---

## Google Cloud Setup

### Enable APIs

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable:
   - **Google Sheets API**
   - **Google Drive API**

### Create Service Account

1. APIs & Services > Credentials
2. Create Credentials > Service Account
3. Download JSON key as `credentials.json`
4. Share your Google Sheet with the service account email (Editor access)

### Payment Screenshots Storage

- Screenshots are uploaded to Google Drive
- Folder: `PepHaul_Payments`
- Files named: `{ORDER_ID}_payment.jpg`
- Links saved in sheet and viewable by anyone with link

---

## Render Deployment

### Environment Variables on Render

| Key | Value |
|-----|-------|
| `GOOGLE_SHEETS_ID` | Your sheet ID |
| `GOOGLE_CREDENTIALS_JSON` | Entire credentials.json content |
| `ADMIN_PASSWORD` | Secure password |
| `SECRET_KEY` | Random string for sessions |
| `FLASK_DEBUG` | `false` |

### Deploy Steps

1. Push to GitHub
2. Connect repo on Render
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn app:app`
5. Add environment variables
6. Deploy!

---

## Order Status Flow

```
New Order → Pending → [Customer can edit/cancel]
                   ↓
            Locked → [No more edits]
                   ↓
            Completed

Payment: Unpaid → Paid (after screenshot upload)
```

---

## Troubleshooting

### "Product is locked"
- Product reached max kits OR admin manually locked
- Check Admin Panel to unlock

### Payment upload fails
- Ensure Google Drive API is enabled
- Check service account has Drive access
- Verify credentials.json is correct

### Orders not saving
- Check sheet sharing (service account needs Editor)
- Verify GOOGLE_SHEETS_ID is correct

### Admin login fails
- Check ADMIN_PASSWORD in .env
- Default: `pephaul2024`
