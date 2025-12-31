"""
PepHaul Order Form - Web Application
Full order management with payment tracking and admin controls
"""

from flask import Flask, render_template, request, jsonify, session
import requests
import json
import os
import base64
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import defaultdict
from functools import wraps
import secrets
import time
from validate_syntax import validate_file

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))

# Configuration
ADMIN_FEE_PHP = float(os.getenv('ADMIN_FEE_PHP', 300))
FALLBACK_EXCHANGE_RATE = float(os.getenv('FALLBACK_EXCHANGE_RATE', 59.20))
GOOGLE_SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID', '18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'pephaul2024')  # Change in production!
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')  # Create bot via @BotFather
TELEGRAM_ADMIN_CHAT_ID = os.getenv('TELEGRAM_ADMIN_CHAT_ID', '')  # Admin's Telegram chat ID (single, for backward compatibility)
TELEGRAM_ADMIN_CHAT_IDS = os.getenv('TELEGRAM_ADMIN_CHAT_IDS', '')  # Multiple admin chat IDs (comma-separated)
TELEGRAM_BOT_USERNAME = os.getenv('TELEGRAM_BOT_USERNAME', 'pephaul_bot')  # Bot username (without @)

# Simple cache to reduce Google Sheets API calls
_cache = {}
_cache_timestamps = {}
CACHE_DURATION = 60  # seconds - default fallback cache duration

def _normalize_order_sheet_headers(headers):
    """
    Normalize PepHaul Entry headers so lookups are stable even if the sheet header row is malformed.
    - Strips whitespace
    - If first header cell is blank, treat it as 'Order ID' (common real-world issue)
    - Any other blank headers become 'Unnamed_{idx}'
    """
    normalized = []
    for idx, h in enumerate(headers or []):
        hs = str(h).strip()
        if not hs:
            if idx == 0:
                hs = 'Order ID'
            else:
                hs = f'Unnamed_{idx}'
        normalized.append(hs)
    return normalized

def _normalize_order_record_keys(record):
    """
    Normalize keys on a single order record:
    - strip whitespace from keys
    - map blank key (often from blank A1 header) to 'Order ID'
    - prefer non-empty values when collisions happen
    """
    if not isinstance(record, dict):
        return record
    out = {}
    for k, v in record.items():
        ks = str(k).strip()
        if not ks:
            ks = 'Order ID'
        # Prefer existing non-empty values if we collide
        if ks in out:
            existing = out.get(ks, '')
            if (not str(existing).strip()) and str(v).strip():
                out[ks] = v
        else:
            out[ks] = v
    return out

def get_cached(key, fetch_func, cache_duration=CACHE_DURATION):
    """Get cached data or fetch if expired - with rate limit protection"""
    now = time.time()
    if key in _cache and key in _cache_timestamps:
        if now - _cache_timestamps[key] < cache_duration:
            return _cache[key]
    
    # Cache miss or expired - fetch new data with retry logic
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            data = fetch_func()
            # Only cache non-None values
            if data is not None:
                _cache[key] = data
                _cache_timestamps[key] = now
            return data
        except Exception as e:
            error_str = str(e)
            # Check for rate limit error
            if ('429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'RATE_LIMIT_EXCEEDED' in error_str) and attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                print(f"Rate limit hit for {key}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
                continue
            # If it's not a rate limit error or we've exhausted retries, raise
            raise

def clear_cache(key=None):
    """Clear specific cache key or all cache"""
    if key:
        _cache.pop(key, None)
        _cache_timestamps.pop(key, None)
    else:
        _cache.clear()
        _cache_timestamps.clear()

def resolve_telegram_recipient(recipient):
    """
    Resolve Telegram recipient to chat ID.
    Accepts: chat ID (numeric string) or username (with/without @)
    Returns: chat_id (string) or None if not found
    """
    if not recipient:
        return None
    
    recipient = recipient.strip()
    
    # If it's already a numeric chat ID, return as-is
    if recipient.lstrip('-').isdigit():
        return recipient
    
    # It's a username - normalize it (remove @ if present, lowercase)
    username = recipient.lstrip('@').lower()
    
    # First, check the telegram_customers mapping (users who have messaged the bot)
    chat_id = telegram_customers.get(username) or telegram_customers.get(f"@{username}")
    if chat_id:
        return str(chat_id)
    
    # Try to get chat ID from Telegram API (only works if user has messaged the bot)
    if TELEGRAM_BOT_TOKEN:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChat"
            data = {'chat_id': f"@{username}"}
            response = requests.post(url, data=data, timeout=5)
            if response.status_code == 200:
                result = response.json()
                if result.get('ok') and result.get('result'):
                    chat_id = str(result['result'].get('id'))
                    # Cache it for future use
                    telegram_customers[username] = chat_id
                    telegram_customers[f"@{username}"] = chat_id
                    print(f"Auto-resolved Telegram username @{username} to chat_id: {chat_id}")
                    return chat_id
        except Exception as e:
            print(f"Could not auto-resolve @{username} via API: {e}")
    
    return None

def send_telegram_notification(message, parse_mode='HTML'):
    """Send notification to admin(s) via Telegram bot - supports multiple recipients (chat IDs or usernames)"""
    if not TELEGRAM_BOT_TOKEN:
        print("Telegram bot token not configured - skipping notification")
        return False
    
    # Get list of recipients (can be chat IDs or usernames)
    recipients = []
    
    # First, check for multiple recipients (comma-separated)
    if TELEGRAM_ADMIN_CHAT_IDS:
        recipients = [r.strip() for r in TELEGRAM_ADMIN_CHAT_IDS.split(',') if r.strip()]
    
    # Also include single recipient for backward compatibility (if not already in list)
    if TELEGRAM_ADMIN_CHAT_ID and TELEGRAM_ADMIN_CHAT_ID not in recipients:
        recipients.append(TELEGRAM_ADMIN_CHAT_ID)
    
    if not recipients:
        print("No Telegram admin recipients configured - skipping notification")
        return False
    
    # Resolve all recipients to chat IDs
    chat_ids = []
    unresolved = []
    
    for recipient in recipients:
        chat_id = resolve_telegram_recipient(recipient)
        if chat_id:
            if chat_id not in chat_ids:  # Avoid duplicates
                chat_ids.append(chat_id)
        else:
            unresolved.append(recipient)
    
    # Warn about unresolved recipients
    if unresolved:
        print(f"⚠️ Could not resolve Telegram recipients: {', '.join(unresolved)}")
        print(f"   These users need to message @{TELEGRAM_BOT_USERNAME} first to register their chat ID")
    
    if not chat_ids:
        print("No valid Telegram chat IDs found - skipping notification")
        return False
    
    # Send notification to all resolved chat IDs
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    success_count = 0
    failed_count = 0
    
    for chat_id in chat_ids:
        try:
            data = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                success_count += 1
                print(f"Telegram notification sent successfully to chat_id: {chat_id}")
            else:
                failed_count += 1
                print(f"Telegram notification failed for chat_id {chat_id}: {response.text}")
        except Exception as e:
            failed_count += 1
            print(f"Error sending Telegram notification to chat_id {chat_id}: {e}")
    
    # Return True if at least one notification succeeded
    return success_count > 0
VIALS_PER_KIT = 10
MAX_KITS_DEFAULT = 100  # Default max kits per product

# Google Sheets and Drive Configuration
sheets_client = None
drive_service = None

def init_google_services():
    """Initialize Google Sheets and Drive clients"""
    global sheets_client, drive_service
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
            'https://www.googleapis.com/auth/drive.file'
        ]
        
        print(f"GOOGLE_CREDENTIALS_JSON exists: {bool(creds_json)}")
        print(f"GOOGLE_CREDENTIALS_JSON length: {len(creds_json) if creds_json else 0}")
        
        if creds_json:
            try:
                creds_dict = json.loads(creds_json)
                print(f"Credentials parsed successfully. Service account: {creds_dict.get('client_email', 'unknown')}")
                creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                sheets_client = gspread.authorize(creds)
                print("Sheets client initialized")
                drive_service = build('drive', 'v3', credentials=creds)
                print("Drive service initialized")
                print("✅ Google services initialized from environment variable")
            except json.JSONDecodeError as je:
                print(f"❌ JSON parse error: {je}")
                print(f"First 100 chars of creds: {creds_json[:100] if creds_json else 'empty'}")
        elif os.path.exists('pephaul-order-form-credentials.json'):
            creds = Credentials.from_service_account_file('pephaul-order-form-credentials.json', scopes=scopes)
            sheets_client = gspread.authorize(creds)
            drive_service = build('drive', 'v3', credentials=creds)
            print("✅ Google services initialized from pephaul-order-form-credentials.json")
        elif os.path.exists('credentials.json'):
            creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
            sheets_client = gspread.authorize(creds)
            drive_service = build('drive', 'v3', credentials=creds)
            print("✅ Google services initialized from credentials.json")
        else:
            print("❌ No Google credentials found - set GOOGLE_CREDENTIALS_JSON env variable")
            
    except Exception as e:
        import traceback
        print(f"❌ Error initializing Google services: {e}")
        traceback.print_exc()

def ensure_worksheets_exist():
    """Ensure all required worksheets exist"""
    if not sheets_client:
        return
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        existing_sheets = [ws.title for ws in spreadsheet.worksheets()]
        
        # PepHaul Entry tab - check for old name and rename, or create new
        if 'PepHaul Entry' in existing_sheets and 'PepHaul Entry-01' not in existing_sheets:
            # Rename existing "PepHaul Entry" to "PepHaul Entry-01"
            try:
                old_worksheet = spreadsheet.worksheet('PepHaul Entry')
                old_worksheet.update_title('PepHaul Entry-01')
                print("✅ Renamed 'PepHaul Entry' to 'PepHaul Entry-01'")
            except Exception as e:
                print(f"⚠️ Could not rename tab: {e}")
        
        # Create PepHaul Entry-01 if it doesn't exist
        if 'PepHaul Entry-01' not in existing_sheets:
            worksheet = spreadsheet.add_worksheet(title='PepHaul Entry-01', rows=1000, cols=25)
            headers = [
                'Order ID', 'Order Date', 'Name', 'Telegram Username', 'Supplier',
                'Product Code', 'Product Name', 'Order Type', 'QTY', 'Unit Price USD',
                'Line Total USD', 'Exchange Rate', 'Line Total PHP', 'Admin Fee PHP',
                'Grand Total PHP', 'Order Status', 'Locked', 'Payment Status', 
                'Remarks', 'Link to Payment', 'Payment Date', 'Full Name', 'Contact Number', 'Mailing Address', 'Tracking Number'
            ]
            worksheet.update('A1:Y1', [headers])
        
        # Product Locks tab (for admin)
        if 'Product Locks' not in existing_sheets:
            worksheet = spreadsheet.add_worksheet(title='Product Locks', rows=200, cols=5)
            headers = ['Product Code', 'Max Kits', 'Is Locked', 'Locked Date', 'Locked By']
            worksheet.update('A1:E1', [headers])
        
        # Price List tab (for products) - create if doesn't exist
        if 'Price List' not in existing_sheets:
            worksheet = spreadsheet.add_worksheet(title='Price List', rows=1000, cols=6)
            headers = ['Product Code', 'Product Name', 'USD Kit Price', 'USD Price/Vial', 'Vials/Kit']
            worksheet.update('A1:E1', [headers])
            # Add a note row
            worksheet.update('A2', [['TR5', 'Tirzepatide - 5mg', '45', '4.5', '10']])
        
            
    except Exception as e:
        print(f"Error ensuring worksheets: {e}")


def get_product_locks():
    """Get product lock settings from Google Sheets"""
    if not sheets_client:
        return {}
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = spreadsheet.worksheet('Product Locks')
        records = worksheet.get_all_records()
        
        locks = {}
        for record in records:
            code = record.get('Product Code', '')
            if code:
                locks[code] = {
                    'max_kits': int(record.get('Max Kits', MAX_KITS_DEFAULT) or MAX_KITS_DEFAULT),
                    'is_locked': str(record.get('Is Locked', '')).lower() == 'yes',
                    'locked_date': record.get('Locked Date', ''),
                    'locked_by': record.get('Locked By', '')
                }
        return locks
    except:
        return {}

def set_product_lock(product_code, is_locked, max_kits=None, admin_name='Admin'):
    """Set product lock status"""
    if not sheets_client:
        print("❌ Error: sheets_client not initialized")
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Ensure Product Locks worksheet exists
        try:
            worksheet = spreadsheet.worksheet('Product Locks')
        except Exception as e:
            print(f"⚠️ Product Locks worksheet not found, creating it...")
            worksheet = spreadsheet.add_worksheet(title='Product Locks', rows=100, cols=5)
            # Add headers
            worksheet.update('A1:E1', [['Product Code', 'Max Kits', 'Is Locked', 'Locked Date', 'Locked By']])
        
        # Ensure headers exist
        try:
            headers = worksheet.row_values(1)
            if not headers or headers[0] != 'Product Code':
                worksheet.update('A1:E1', [['Product Code', 'Max Kits', 'Is Locked', 'Locked Date', 'Locked By']])
        except:
            worksheet.update('A1:E1', [['Product Code', 'Max Kits', 'Is Locked', 'Locked Date', 'Locked By']])
        
        # Find existing row or add new
        try:
            cell = worksheet.find(product_code)
            row = cell.row
        except Exception as e:
            # Product not found, add new row
            all_values = worksheet.get_all_values()
            row = len(all_values) + 1
            if row == 1:  # Only header row exists
                row = 2
            worksheet.update_cell(row, 1, product_code)
        
        # Update values
        if max_kits is not None:
            worksheet.update_cell(row, 2, max_kits)
        worksheet.update_cell(row, 3, 'Yes' if is_locked else 'No')
        worksheet.update_cell(row, 4, datetime.now().strftime('%Y-%m-%d %H:%M:%S') if is_locked else '')
        worksheet.update_cell(row, 5, admin_name if is_locked else '')
        
        print(f"✅ Product {product_code} lock status updated: {'Locked' if is_locked else 'Unlocked'}")
        return True
    except Exception as e:
        print(f"❌ Error setting product lock for {product_code}: {e}")
        import traceback
        traceback.print_exc()
        return False

# In-memory order form lock (persists while server runs, or use Google Sheets for persistence)
_order_form_locked = False
_order_form_lock_message = ""

# --- Rich text sanitization (used for lock message) ---
# We store formatted lock messages as *sanitized HTML* so the public page can render safely.
from html.parser import HTMLParser
from html import escape as _html_escape
import re as _re

_ALLOWED_LOCK_TAGS = {
    'b', 'strong', 'i', 'em', 'u', 'br',
    'p', 'div', 'span',
    'h1', 'h2', 'h3', 'h4',
    'ul', 'ol', 'li'
}

_ALLOWED_STYLE_PROPS = {'text-align', 'color', 'font-family', 'font-size', 'font-weight'}
_ALLOWED_TEXT_ALIGN = {'left', 'center', 'right', 'justify'}
_ALLOWED_FONTS = {
    'Outfit', 'Inter', 'Poppins', 'Arial', 'Helvetica', 'Georgia', 'Times New Roman', 'Courier New',
    'JetBrains Mono', 'Verdana', 'Tahoma'
}

_COLOR_RE = _re.compile(r'^(#[0-9a-fA-F]{3,8}|rgba?\([0-9\s.,%]+\)|hsla?\([0-9\s.,%]+\)|[a-zA-Z]+)$')
_FONTSIZE_RE = _re.compile(r'^([0-9]{1,3})(px|em|rem|%)$')


def _sanitize_style_value(prop: str, val: str) -> str:
    v = (val or '').strip()
    if not v:
        return ''
    vl = v.lower()
    # Block CSS injection primitives
    if 'url(' in vl or 'expression(' in vl or '@import' in vl:
        return ''
    if prop == 'text-align':
        return vl if vl in _ALLOWED_TEXT_ALIGN else ''
    if prop == 'color':
        return v if _COLOR_RE.match(v.strip()) else ''
    if prop == 'font-family':
        # Take the first font in the list, strip quotes
        first = v.split(',')[0].strip().strip('"').strip("'")
        return first if first in _ALLOWED_FONTS else ''
    if prop == 'font-size':
        m = _FONTSIZE_RE.match(vl)
        if not m:
            return ''
        num = int(m.group(1))
        unit = m.group(2)
        # Reasonable bounds to avoid giant banners
        if unit == 'px' and (num < 10 or num > 72):
            return ''
        if unit != 'px' and (num < 50 or num > 200):
            return ''
        return f"{num}{unit}"
    if prop == 'font-weight':
        if vl in {'normal', 'bold', 'bolder', 'lighter'}:
            return vl
        if vl.isdigit():
            n = int(vl)
            return str(n) if 100 <= n <= 900 and n % 100 == 0 else ''
        return ''
    return ''


def sanitize_lock_message_html(raw_html: str) -> str:
    """Sanitize lock message HTML (admin-controlled but rendered publicly)."""
    raw_html = str(raw_html or '').strip()
    if not raw_html:
        return ''

    class _Sanitizer(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out = []
            self.stack = []

        def handle_starttag(self, tag, attrs):
            t = (tag or '').lower()
            if t not in _ALLOWED_LOCK_TAGS:
                return

            if t == 'br':
                self.out.append('<br/>')
                return

            clean_style = None
            for (k, v) in (attrs or []):
                kk = (k or '').lower()
                if kk != 'style':
                    continue
                style = v or ''
                parts = []
                for decl in style.split(';'):
                    if ':' not in decl:
                        continue
                    prop, val = decl.split(':', 1)
                    prop = prop.strip().lower()
                    if prop not in _ALLOWED_STYLE_PROPS:
                        continue
                    safe_val = _sanitize_style_value(prop, val)
                    if safe_val:
                        parts.append(f"{prop}: {safe_val}")
                if parts:
                    clean_style = '; '.join(parts)
                break

            if clean_style:
                attr_str = f' style="{_html_escape(clean_style, quote=True)}"'
            else:
                attr_str = ''
            self.out.append(f"<{t}{attr_str}>")
            self.stack.append(t)

        def handle_endtag(self, tag):
            t = (tag or '').lower()
            if t not in _ALLOWED_LOCK_TAGS or t == 'br':
                return
            if t in self.stack:
                while self.stack:
                    top = self.stack.pop()
                    self.out.append(f"</{top}>")
                    if top == t:
                        break

        def handle_data(self, data):
            if data:
                self.out.append(_html_escape(data))

        def handle_entityref(self, name):
            self.out.append(f"&{name};")

        def handle_charref(self, name):
            self.out.append(f"&#{name};")

    s = _Sanitizer()
    try:
        s.feed(raw_html)
        s.close()
    except Exception:
        return _html_escape(raw_html)

    while s.stack:
        top = s.stack.pop()
        s.out.append(f"</{top}>")

    return ''.join(s.out).strip()

# In-memory theme (persists while server runs, or use Google Sheets for persistence)
_current_theme = "default"

def _fetch_order_form_lock():
    """Internal function to fetch lock status from sheets"""
    global _order_form_locked, _order_form_lock_message
    
    # Try to get from Google Sheets for persistence
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            
            # Check if Settings sheet exists
            try:
                worksheet = spreadsheet.worksheet('Settings')
            except:
                # Create Settings sheet if doesn't exist
                worksheet = spreadsheet.add_worksheet(title='Settings', rows=10, cols=5)
                worksheet.update('A1:C1', [['Setting', 'Value', 'Updated']])
                worksheet.update('A2:C2', [['Order Form Locked', 'No', '']])
                worksheet.update('A3:C3', [['Lock Message', '', '']])
                return {'is_locked': False, 'message': ''}
            
            records = worksheet.get_all_records()
            for record in records:
                if record.get('Setting') == 'Order Form Locked':
                    _order_form_locked = str(record.get('Value', '')).lower() == 'yes'
                if record.get('Setting') == 'Lock Message':
                    _order_form_lock_message = sanitize_lock_message_html(record.get('Value', ''))
                    
        except Exception as e:
            print(f"Error getting order form lock: {e}")
    
    return {'is_locked': _order_form_locked, 'message': _order_form_lock_message}

def get_order_form_lock():
    """Get order form lock status (cached)"""
    return get_cached('settings_lock', _fetch_order_form_lock, cache_duration=600)  # 10 minutes - settings rarely change

def set_order_form_lock(is_locked, message=''):
    """Set order form lock status"""
    global _order_form_locked, _order_form_lock_message
    _order_form_locked = is_locked
    _order_form_lock_message = sanitize_lock_message_html(message)
    
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            
            # Ensure Settings sheet exists
            try:
                worksheet = spreadsheet.worksheet('Settings')
            except:
                worksheet = spreadsheet.add_worksheet(title='Settings', rows=10, cols=5)
                worksheet.update('A1:C1', [['Setting', 'Value', 'Updated']])
            
            # Find or create the lock setting row
            all_values = worksheet.get_all_values()
            lock_row = None
            message_row = None
            
            for i, row in enumerate(all_values):
                if row and row[0] == 'Order Form Locked':
                    lock_row = i + 1
                if row and row[0] == 'Lock Message':
                    message_row = i + 1
            
            if lock_row is None:
                lock_row = len(all_values) + 1
                worksheet.update_cell(lock_row, 1, 'Order Form Locked')
            
            if message_row is None:
                message_row = len(all_values) + 2
                worksheet.update_cell(message_row, 1, 'Lock Message')
            
            # Update values
            worksheet.update_cell(lock_row, 2, 'Yes' if is_locked else 'No')
            worksheet.update_cell(lock_row, 3, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            worksheet.update_cell(message_row, 2, _order_form_lock_message)
            worksheet.update_cell(message_row, 3, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            
            # Clear cache since settings changed
            clear_cache('settings_lock')
            
            return True
        except Exception as e:
            print(f"Error setting order form lock: {e}")
            return False
    
    return True

# Order Goal Settings
_order_goal = 1000.0  # Default goal

def _fetch_order_goal():
    """Internal function to fetch order goal from sheets"""
    global _order_goal
    
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            worksheet = spreadsheet.worksheet('Settings')
            records = worksheet.get_all_records()
            
            for record in records:
                if record.get('Setting') == 'Order Goal':
                    try:
                        _order_goal = float(record.get('Value', 1000))
                    except:
                        _order_goal = 1000.0
                    break
        except Exception as e:
            print(f"Error getting order goal: {e}")
    
    return _order_goal

# Theme Management
def _fetch_theme():
    """Internal function to fetch theme from sheets"""
    global _current_theme
    
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            
            try:
                worksheet = spreadsheet.worksheet('Settings')
            except:
                worksheet = spreadsheet.add_worksheet(title='Settings', rows=10, cols=5)
                worksheet.update('A1:C1', [['Setting', 'Value', 'Updated']])
                worksheet.update('A4:C4', [['Theme', 'default', '']])
                return 'default'
            
            records = worksheet.get_all_records()
            for record in records:
                if record.get('Setting') == 'Theme':
                    theme_value = str(record.get('Value', 'default')).strip()
                    if theme_value:
                        _current_theme = theme_value
                    break
        except Exception as e:
            print(f"Error getting theme: {e}")
    
    return _current_theme

def get_theme():
    """Get current theme (cached)"""
    return get_cached('theme', _fetch_theme, cache_duration=600)

def set_theme(theme_name):
    """Set theme"""
    global _current_theme
    
    valid_themes = ['default', 'merry_christmas', 'happy_new_year', 'chinese_new_year', 
                    'summer', 'valentines', 'halloween', 'holy_week']
    
    if theme_name not in valid_themes:
        return False
    
    _current_theme = theme_name
    
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            
            try:
                worksheet = spreadsheet.worksheet('Settings')
            except:
                worksheet = spreadsheet.add_worksheet(title='Settings', rows=10, cols=5)
                worksheet.update('A1:C1', [['Setting', 'Value', 'Updated']])
            
            # Find or create Theme row
            records = worksheet.get_all_records()
            theme_row = None
            for idx, record in enumerate(records, start=2):
                if record.get('Setting') == 'Theme':
                    theme_row = idx
                    break
            
            if not theme_row:
                # Add new row
                all_values = worksheet.get_all_values()
                theme_row = len(all_values) + 1
                worksheet.update_cell(theme_row, 1, 'Theme')
            
            worksheet.update_cell(theme_row, 2, theme_name)
            worksheet.update_cell(theme_row, 3, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            
            # Clear cache so theme is immediately available
            clear_cache('theme')
            
            return True
        except Exception as e:
            print(f"Error setting theme: {e}")
            return False
    
    # Clear cache even if sheets_client is not available
    clear_cache('theme')
    return True

def get_order_goal():
    """Get order goal from Settings sheet (cached)"""
    return get_cached('settings_goal', _fetch_order_goal, cache_duration=600)  # 10 minutes - settings rarely change

def set_order_goal(goal_amount):
    """Set order goal in Settings sheet - optimized to reduce API calls"""
    global _order_goal
    _order_goal = float(goal_amount)
    
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            
            try:
                worksheet = spreadsheet.worksheet('Settings')
            except:
                worksheet = spreadsheet.add_worksheet(title='Settings', rows=10, cols=5)
                worksheet.update('A1:C1', [['Setting', 'Value', 'Updated']])
            
            # Find or create the goal setting row - use batch update to reduce API calls
            all_values = worksheet.get_all_values()
            goal_row = None
            
            for i, row in enumerate(all_values):
                if row and len(row) > 0 and row[0] == 'Order Goal':
                    goal_row = i + 1
                    break
            
            update_data = [[str(goal_amount), datetime.now().strftime('%Y-%m-%d %H:%M:%S')]]
            
            if goal_row is None:
                # New row - use batch update for all 3 cells at once
                goal_row = len(all_values) + 1
                worksheet.update(f'A{goal_row}:C{goal_row}', [['Order Goal', str(goal_amount), datetime.now().strftime('%Y-%m-%d %H:%M:%S')]])
            else:
                # Existing row - batch update only the 2 cells that change (B and C)
                worksheet.update(f'B{goal_row}:C{goal_row}', update_data)
            
            # Clear cache since settings changed
            clear_cache('settings_goal')
            
            return True
        except Exception as e:
            error_str = str(e)
            # Check for rate limit error
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'RATE_LIMIT_EXCEEDED' in error_str:
                print(f"Rate limit exceeded when setting order goal. Please wait a moment and try again.")
                # Don't fail completely - update in-memory value so UI reflects change
                return True  # Return True so UI updates, but log the error
            print(f"Error setting order goal: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    return True

def _fetch_orders_from_sheets():
    """Internal function to fetch orders from sheets (called by cache)"""
    if not sheets_client:
        return []
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Debug: List all available worksheets
        all_worksheets = [ws.title for ws in spreadsheet.worksheets()]
        print(f"📋 Available worksheets in sheet: {all_worksheets}")
        
        # Get current tab name dynamically
        current_tab = get_current_pephaul_tab()
        
        # Check if current tab exists, with fallback logic
        if current_tab not in all_worksheets:
            # Try fallback to PepHaul Entry-01
            if 'PepHaul Entry-01' in all_worksheets:
                current_tab = 'PepHaul Entry-01'
                set_current_pephaul_tab(current_tab)
            elif 'PepHaul Entry' in all_worksheets:
                # Old name exists, will be renamed on next ensure_worksheets_exist call
                current_tab = 'PepHaul Entry'
            else:
                print(f"⚠️ WARNING: '{current_tab}' worksheet not found!")
                print(f"📋 Available worksheets: {', '.join(all_worksheets)}")
                if all_worksheets:
                    print(f"⚠️ Trying first available worksheet: {all_worksheets[0]}")
                    worksheet = spreadsheet.worksheet(all_worksheets[0])
                else:
                    print(f"❌ ERROR: No worksheets found in spreadsheet!")
                    return []
                # Continue with fallback worksheet
            if 'worksheet' not in locals():
                worksheet = spreadsheet.worksheet(current_tab)
        else:
            worksheet = get_pephaul_worksheet(spreadsheet)
            if not worksheet:
                return []
        
        # Check if worksheet has data before trying to get records
        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) <= 1:
            # Empty worksheet or only headers, return empty list
            print(f"⚠️ Worksheet appears empty or only has headers: {len(all_values) if all_values else 0} rows")
            return []
        
        # Log headers for debugging (and normalize them for reliable lookups)
        raw_headers = all_values[0] if all_values else []
        headers = _normalize_order_sheet_headers(raw_headers)
        print(f"📋 Sheet headers (raw, {len(raw_headers)}): {raw_headers[:15]}")
        print(f"📋 Sheet headers (normalized, {len(headers)}): {headers[:15]}")
        print(f"📋 Total rows in sheet (including header): {len(all_values)}")
        
        telegram_col_index = None
        order_id_col_index = None
        for i, header in enumerate(headers):
            header_lower = str(header).lower().strip()
            if 'telegram' in header_lower:
                telegram_col_index = i
                print(f"📋 Found Telegram column at index {i}: '{header}'")
            if 'order id' in header_lower or 'orderid' in header_lower:
                order_id_col_index = i
                print(f"📋 Found Order ID column at index {i}: '{header}'")
        
        # Debug: Show sample raw data rows
        if len(all_values) > 1:
            print(f"📋 Sample raw data rows (first 3 data rows):")
            for i in range(1, min(4, len(all_values))):
                row = all_values[i]
                if order_id_col_index is not None and len(row) > order_id_col_index:
                    print(f"  Row {i+1}: Order ID='{row[order_id_col_index] if len(row) > order_id_col_index else 'N/A'}', Telegram='{row[telegram_col_index] if telegram_col_index is not None and len(row) > telegram_col_index else 'N/A'}'")
        
        # Try get_all_records first (faster, but might preserve bad/blank header keys)
        records = worksheet.get_all_records()
        # Ensure we return a list
        if not isinstance(records, list):
            print(f"⚠️ get_all_records() did not return a list, got: {type(records)}")
            records = []
        
        # Normalize keys so blank/whitespace headers don't break lookups (e.g., blank A1 header)
        if records:
            records = [_normalize_order_record_keys(r) for r in records]

        print(f"📋 get_all_records() returned {len(records)} records")
        
        # Verify records match expected count (should be all_values - 1 for header)
        expected_count = len(all_values) - 1
        if len(records) != expected_count:
            print(f"⚠️ WARNING: Record count mismatch! Expected {expected_count} records (from {len(all_values)} rows - 1 header), but got {len(records)}")
            print(f"📋 This might mean some rows are empty or get_all_records() stopped early")
            
            # Fallback: Build records manually from raw values to ensure we get everything
            if len(all_values) > 1 and headers:
                print(f"📋 Building records manually from raw values to capture all rows...")
                manual_records = []
                for row_idx, row in enumerate(all_values[1:], start=2):  # Skip header row
                    if len(row) < len(headers):
                        # Pad row if shorter than headers
                        row = row + [''] * (len(headers) - len(row))
                    elif len(row) > len(headers):
                        # Truncate row if longer than headers
                        row = row[:len(headers)]
                    
                    # Create dict from row
                    record = {}
                    for col_idx, header in enumerate(headers):
                        if col_idx < len(row):
                            value = row[col_idx]
                            # Only include non-empty values or keep empty strings for consistency
                            record[header] = value if value else ''
                        else:
                            record[header] = ''
                    
                    # Only add record if it has at least one non-empty value (skip completely empty rows)
                    if any(str(v).strip() for v in record.values()):
                        manual_records.append(record)
                
                print(f"📋 Manual record building found {len(manual_records)} records with data")
                
                # Use manual records if we got more than get_all_records
                if len(manual_records) > len(records):
                    print(f"📋 Using manually built records ({len(manual_records)} vs {len(records)} from get_all_records)")
                    records = manual_records
                else:
                    print(f"📋 Keeping get_all_records() results ({len(records)} records)")
        
        # Debug: Log first record's keys to see what columns are available
        if records and len(records) > 0:
            first_record_keys = list(records[0].keys())
            print(f"📋 Available columns in records ({len(first_record_keys)}): {first_record_keys}")
            
            # Check for Order ID column
            order_id_keys = [k for k in first_record_keys if 'order' in k.lower() and 'id' in k.lower()]
            if order_id_keys:
                print(f"📋 Order ID-related columns found: {order_id_keys}")
                # Show sample Order IDs
                for i, record in enumerate(records[:5]):
                    for oid_key in order_id_keys:
                        value = record.get(oid_key, None)
                        if value:
                            print(f"📋 Record {i+1} Order ID [{oid_key}]: {repr(str(value))}")
                            break
            
            telegram_keys = [k for k in first_record_keys if 'telegram' in k.lower()]
            if telegram_keys:
                print(f"📋 Telegram-related columns found: {telegram_keys}")
                # Log sample telegram values with their exact representation
                for i, record in enumerate(records[:10]):
                    for tg_key in telegram_keys:
                        value = record.get(tg_key, None)
                        if value is not None:
                            value_repr = repr(str(value))  # Show exact string representation including whitespace
                            order_id_val = record.get(order_id_keys[0] if order_id_keys else 'Order ID', 'N/A')
                            print(f"📋 Record {i+1} [Order: {order_id_val}] [{tg_key}]: {value_repr} (type: {type(value).__name__})")
                            break  # Only log first telegram column found
        
        return records
    except IndexError as e:
        print(f"Error reading orders (index out of range - worksheet may be empty or malformed): {e}")
        import traceback
        traceback.print_exc()
        return []
    except Exception as e:
        print(f"Error reading orders: {e}")
        import traceback
        traceback.print_exc()
        return []

def _enrich_orders_with_supplier(orders):
    """Enrich orders with supplier information based on product code if supplier is missing"""
    if not orders:
        return orders
    
    # Get products to build product_code -> supplier map
    try:
        products = get_products()
        # Build map: for unique codes, map to supplier; for duplicate codes, create a list
        code_to_supplier_map = {}
        code_to_suppliers_map = defaultdict(set)
        for p in products:
            code = p['code']
            supplier = p.get('supplier', 'Default')
            code_to_suppliers_map[code].add(supplier)
            # For unique codes, store supplier
            if code not in code_to_supplier_map:
                code_to_supplier_map[code] = supplier
        
        # Enrich orders with supplier
        enriched_orders = []
        for order in orders:
            enriched_order = order.copy()
            order_supplier = order.get('Supplier', '') or order.get('supplier', '')
            product_code = order.get('Product Code', '')
            
            # If supplier is missing, infer from product code
            if not order_supplier and product_code:
                if product_code in code_to_supplier_map:
                    # Unique code - use mapped supplier
                    enriched_order['Supplier'] = code_to_supplier_map[product_code]
                elif product_code in code_to_suppliers_map:
                    # Multiple suppliers have this code - default to first one (usually WWB)
                    default_supplier = sorted(code_to_suppliers_map[product_code])[0]
                    enriched_order['Supplier'] = default_supplier
                else:
                    # Product code not found - keep empty or set to Default
                    enriched_order['Supplier'] = 'Default'
            elif order_supplier:
                # Supplier already exists - keep it
                enriched_order['Supplier'] = order_supplier
            
            enriched_orders.append(enriched_order)
        
        return enriched_orders
    except Exception as e:
        print(f"⚠️ Error enriching orders with supplier: {e}")
        # Return original orders if enrichment fails
        return orders

def get_orders_from_sheets():
    """Read existing orders from PepHaul Entry tab (cached)"""
    orders = get_cached('orders', _fetch_orders_from_sheets, cache_duration=180)  # 3 minutes - balance freshness/performance
    # Enrich orders with supplier information if missing
    return _enrich_orders_with_supplier(orders)

def get_order_by_id(order_id):
    """Get a specific order by ID"""
    orders = get_orders_from_sheets()
    # Normalize record keys defensively (covers cases where records were cached pre-normalization)
    orders = [_normalize_order_record_keys(o) for o in orders] if isinstance(orders, list) else orders
    order_items = [o for o in orders if str(o.get('Order ID', '')).strip() == str(order_id).strip()]
    
    if not order_items:
        return None
    
    # Reconstruct order
    first_item = order_items[0]
    
    # Find telegram column dynamically (handle variations)
    telegram_value = None
    for key in first_item.keys():
        if 'telegram' in key.lower():
            telegram_value = first_item.get(key, '')
            if telegram_value:
                break
    
    # Fallback to common variations
    if not telegram_value:
        telegram_value = (
            first_item.get('Telegram Username', '') or 
            first_item.get('telegram username', '') or 
            first_item.get('Telegram Username ', '') or
            first_item.get('TelegramUsername', '') or
            ''
        )
    
    # Get customer name from Column C ("Name")
    customer_full_name = first_item.get('Name', first_item.get('Full Name', ''))
    
    # Get mailing details - these are stored in columns U (Full Name/mailing_name), V (Contact Number/mailing_phone), W (Mailing Address)
    # When shipping details are added, Column U is updated to contain mailing receiver name
    mailing_address = first_item.get('Mailing Address', '')  # Column W
    
    # If mailing address exists, Column U contains mailing receiver name, Column V contains mailing phone
    # Otherwise, these columns might be empty or contain customer info
    if mailing_address and mailing_address.strip():
        mailing_name = first_item.get('Full Name', '')  # Column U - mailing receiver name
        mailing_phone = first_item.get('Contact Number', '')  # Column V - mailing phone
    else:
        mailing_name = ''
        mailing_phone = ''
    
    # Get tracking number from column X (24)
    tracking_number = first_item.get('Tracking Number', '')
    
    order = {
        'order_id': order_id,
        'order_date': first_item.get('Order Date', ''),
        'full_name': customer_full_name,
        'telegram': telegram_value,
        'exchange_rate': float(first_item.get('Exchange Rate', FALLBACK_EXCHANGE_RATE) or FALLBACK_EXCHANGE_RATE),
        'admin_fee_php': float(first_item.get('Admin Fee PHP', ADMIN_FEE_PHP) or 0),
        'grand_total_php': float(first_item.get('Grand Total PHP', 0) or 0),
        'status': first_item.get('Order Status', 'Pending'),
        'locked': str(first_item.get('Locked', 'No')).lower() == 'yes',
        'payment_status': first_item.get('Payment Status', first_item.get('Confirmed Paid?', 'Unpaid')),
        'payment_screenshot': first_item.get('Link to Payment', first_item.get('Payment Screenshot Link', first_item.get('Payment Screenshot', ''))),
        'contact_number': mailing_phone if mailing_address else '',  # Use mailing phone if shipping details exist
        'mailing_address': mailing_address,
        'mailing_name': mailing_name,
        'mailing_phone': mailing_phone,
        'tracking_number': tracking_number,
        'items': []
    }
    
    for item in order_items:
        if item.get('Product Code'):
            qty = int(item.get('QTY', 0) or 0)
            # Only include items with quantity > 0
            if qty > 0:
                order['items'].append({
                    'product_code': item.get('Product Code', ''),
                    'product_name': item.get('Product Name', ''),
                    'order_type': item.get('Order Type', 'Vial'),
                    'qty': qty,
                    'unit_price_usd': float(item.get('Unit Price USD', 0) or 0),
                    'line_total_usd': float(item.get('Line Total USD', 0) or 0),
                    'line_total_php': float(item.get('Line Total PHP', 0) or 0)
                })
    
    # Recalculate subtotal from items (only qty > 0)
    order['subtotal_usd'] = sum(item.get('line_total_usd', 0) for item in order['items'])
    order['subtotal_php'] = sum(item.get('line_total_php', 0) for item in order['items'])
    
    # Ensure grand total is correct
    if order['grand_total_php'] == 0 or order['grand_total_php'] != (order['subtotal_php'] + ADMIN_FEE_PHP):
        order['grand_total_php'] = order['subtotal_php'] + ADMIN_FEE_PHP
    
    return order

def save_order_to_sheets(order_data, order_id=None):
    """Save order to PepHaul Entry tab
    
    Format: All rows have Order ID, Date, Customer info (for easy lookup).
    Only first row has Grand Total, Admin Fee, Order Status, Payment columns.
    """
    if not sheets_client:
        return None
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return None
        
        # Generate or use existing order ID
        if not order_id:
            order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        order_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Get next row
        all_values = worksheet.get_all_values()
        next_row = len(all_values) + 1
        
        # Prepare rows - ALL rows have Order ID, Date, Customer info for easy lookup
        rows_to_add = []
        for i, item in enumerate(order_data['items']):
            row = [
                order_id,                           # Column A: Order ID
                order_date,                         # Column B: Order Date
                order_data['full_name'],            # Column C: Name
                order_data['telegram'],             # Column D: Telegram Username
                item.get('supplier', ''),           # Column E: Supplier
                item['product_code'],               # Column F: Product Code
                item.get('product_name', ''),       # Column G: Product Name
                item['order_type'],                 # Column H: Order Type
                item['qty'],                        # Column I: QTY
                item.get('unit_price_usd', 0),      # Column J: Unit Price USD
                item.get('line_total_usd', 0),      # Column K: Line Total USD
                order_data.get('exchange_rate', FALLBACK_EXCHANGE_RATE),  # Column L: Exchange Rate
                item.get('line_total_php', 0),      # Column M: Line Total PHP
                ADMIN_FEE_PHP if i == 0 else '',    # Column N: Admin Fee PHP (only first row)
                order_data.get('grand_total_php', 0) if i == 0 else '',  # Column O: Grand Total PHP (only first row)
                'Pending' if i == 0 else '',        # Column P: Order Status (only first row)
                'No' if i == 0 else '',             # Column Q: Locked (only first row)
                'Unpaid' if i == 0 else '',         # Column R: Payment Status (only first row)
                '' if i == 0 else '',               # Column S: Remarks (only first row)
                '',                                 # Column T: Link to Payment (only first row)
                '',                                 # Column U: Payment Date (only first row)
                order_data.get('full_name', '') if i == 0 else '',         # Column V: Full Name (only first row)
                order_data.get('contact_number', '') if i == 0 else '',    # Column W: Contact Number (only first row)
                order_data.get('mailing_address', '') if i == 0 else '',    # Column X: Mailing Address (only first row)
                ''                                  # Column Y: Tracking Number (only first row)
            ]
            rows_to_add.append(row)
        
        if rows_to_add:
            end_row = next_row + len(rows_to_add) - 1
            worksheet.update(f'A{next_row}:Y{end_row}', rows_to_add)
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        return order_id
        
    except Exception as e:
        print(f"Error saving order: {e}")
        return None

def update_order_status(order_id, status=None, locked=None, payment_status=None, payment_screenshot=None):
    """Update order status in Google Sheets"""
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return None
        
        # Get headers to find column indices dynamically
        all_values = worksheet.get_all_values()
        if not all_values:
            print("No data found in PepHaul Entry sheet")
            return False
        
        headers = [h.strip() if h else '' for h in all_values[0]]
        
        # Normalize first header if blank (as we did in _fetch_orders_from_sheets)
        if headers and (not headers[0] or headers[0].strip() == ''):
            headers[0] = 'Order ID'
        
        # Find column indices dynamically
        col_order_status = headers.index('Order Status') if 'Order Status' in headers else None
        col_locked = headers.index('Locked') if 'Locked' in headers else None
        col_payment_status = headers.index('Payment Status') if 'Payment Status' in headers else None
        col_payment_link = headers.index('Link to Payment') if 'Link to Payment' in headers else None
        col_payment_date = headers.index('Payment Date') if 'Payment Date' in headers else None
        
        # Find all rows with this order ID
        cells = worksheet.findall(order_id)
        
        if not cells:
            print(f"Order ID {order_id} not found in sheet")
            return False
        
        # Get the first row (order header row) - this is where order-level fields are stored
        first_row = cells[0].row
        
        # Update order-level fields on the first row only
        if status and col_order_status is not None:
            worksheet.update_cell(first_row, col_order_status + 1, status)  # +1 because update_cell is 1-indexed
        if locked is not None and col_locked is not None:
            worksheet.update_cell(first_row, col_locked + 1, 'Yes' if locked else 'No')
            print(f"🔒 Updating Locked column (index {col_locked + 1}) to {'Yes' if locked else 'No'} for order {order_id}")
        if payment_status and col_payment_status is not None:
            worksheet.update_cell(first_row, col_payment_status + 1, payment_status)
        if payment_screenshot:
            if col_payment_link is not None:
                worksheet.update_cell(first_row, col_payment_link + 1, payment_screenshot)
            if col_payment_date is not None:
                worksheet.update_cell(first_row, col_payment_date + 1, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        print(f"✅ Updated order {order_id}: status={status}, locked={locked}, payment_status={payment_status}")
        return True
    except Exception as e:
        print(f"Error updating order: {e}")
        import traceback
        traceback.print_exc()
        return False

def add_items_to_order(order_id, new_items, exchange_rate, telegram_username=None, is_post_payment=False):
    """Add items to an existing order
    
    If order is paid, creates a NEW separate order entry for unpaid items (preserves existing paid items).
    If order is unpaid, adds items to existing order.
    
    Args:
        order_id: Order ID to update (if None, will find by telegram_username)
        new_items: List of items to add
        exchange_rate: Exchange rate for calculations
        telegram_username: Optional telegram username to find order if order_id not provided
        is_post_payment: If True, order is paid - create new order entry instead of modifying existing
    """
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return None
        
        # Get all existing data
        all_values = worksheet.get_all_values()
        headers = all_values[0] if all_values else []
        
        # Find column indices (updated for Supplier in column E)
        col_indices = {
            'order_id': headers.index('Order ID') if 'Order ID' in headers else 0,
            'supplier': headers.index('Supplier') if 'Supplier' in headers else 4,
            'product_code': headers.index('Product Code') if 'Product Code' in headers else 5,
            'order_type': headers.index('Order Type') if 'Order Type' in headers else 7,
            'qty': headers.index('QTY') if 'QTY' in headers else 8,
            'unit_price': headers.index('Unit Price USD') if 'Unit Price USD' in headers else 9,
            'line_total_usd': headers.index('Line Total USD') if 'Line Total USD' in headers else 10,
            'line_total_php': headers.index('Line Total PHP') if 'Line Total PHP' in headers else 12,
        }
        
        col_telegram = headers.index('Telegram Username') if 'Telegram Username' in headers else 3
        
        # If order_id not provided, find by telegram username
        if not order_id and telegram_username:
            telegram_normalized = telegram_username.lower().strip().lstrip('@')
            # Find first order row matching telegram username
            for row_num, row in enumerate(all_values[1:], start=2):
                if len(row) > col_telegram:
                    row_telegram = str(row[col_telegram]).lower().strip().lstrip('@')
                    if row_telegram == telegram_normalized:
                        # Found matching order, get order_id from this row
                        if len(row) > col_indices['order_id']:
                            order_id = row[col_indices['order_id']]
                            break
            
            if not order_id:
                print(f"Order not found for telegram username: {telegram_username}")
                return False
        
        if not order_id:
            print("No order_id or telegram_username provided")
            return False
        
        # Find the first row of this order and get order-level info
        first_order_row = None
        order_info = {
            'full_name': '', 
            'telegram': '', 
            'order_date': '',
            'admin_fee': ADMIN_FEE_PHP,
            'order_status': 'Pending',
            'locked': 'No',
            'payment_status': 'Unpaid',
            'payment_screenshot': '',
            'payment_date': '',
            'contact_number': '',
            'mailing_address': ''
        }
        
        col_full_name = headers.index('Name') if 'Name' in headers else (headers.index('Full Name') if 'Full Name' in headers else 2)
        col_order_date = headers.index('Order Date') if 'Order Date' in headers else 1
        col_admin_fee = headers.index('Admin Fee PHP') if 'Admin Fee PHP' in headers else 12
        col_order_status = headers.index('Order Status') if 'Order Status' in headers else 14
        col_locked = headers.index('Locked') if 'Locked' in headers else 15
        col_payment_status = headers.index('Payment Status') if 'Payment Status' in headers else 16
        col_payment_link = headers.index('Link to Payment') if 'Link to Payment' in headers else 18
        col_payment_date = headers.index('Payment Date') if 'Payment Date' in headers else 19
        col_contact = headers.index('Contact Number') if 'Contact Number' in headers else 21
        col_mailing = headers.index('Mailing Address') if 'Mailing Address' in headers else 22
        
        for row_num, row in enumerate(all_values[1:], start=2):
            if len(row) > col_indices['order_id'] and row[col_indices['order_id']] == order_id:
                if first_order_row is None:
                    first_order_row = row_num
                    # Get order-level info from first row
                    first_row_data = all_values[row_num - 1]  # 0-indexed
                    order_info['full_name'] = first_row_data[col_full_name] if len(first_row_data) > col_full_name else ''
                    order_info['telegram'] = first_row_data[col_telegram] if len(first_row_data) > col_telegram else ''
                    order_info['order_date'] = first_row_data[col_order_date] if len(first_row_data) > col_order_date else ''
                    order_info['admin_fee'] = float(first_row_data[col_admin_fee]) if len(first_row_data) > col_admin_fee and first_row_data[col_admin_fee] else ADMIN_FEE_PHP
                    order_info['order_status'] = first_row_data[col_order_status] if len(first_row_data) > col_order_status and first_row_data[col_order_status] else 'Pending'
                    order_info['locked'] = first_row_data[col_locked] if len(first_row_data) > col_locked and first_row_data[col_locked] else 'No'
                    order_info['payment_status'] = first_row_data[col_payment_status] if len(first_row_data) > col_payment_status and first_row_data[col_payment_status] else 'Unpaid'
                    order_info['payment_screenshot'] = first_row_data[col_payment_link] if len(first_row_data) > col_payment_link and first_row_data[col_payment_link] else ''
                    order_info['payment_date'] = first_row_data[col_payment_date] if len(first_row_data) > col_payment_date and first_row_data[col_payment_date] else ''
                    order_info['contact_number'] = first_row_data[col_contact] if len(first_row_data) > col_contact and first_row_data[col_contact] else ''
                    order_info['mailing_address'] = first_row_data[col_mailing] if len(first_row_data) > col_mailing and first_row_data[col_mailing] else ''
                break
        
        if not first_order_row:
            print(f"Order {order_id} not found in sheet")
            return False
        
        # Check if order is paid
        is_paid = order_info['payment_status'] and order_info['payment_status'].lower() == 'paid'
        
        # Filter out 0 quantity items from new_items
        items_to_add = [item for item in new_items if item.get('qty', 0) > 0]
        
        if not items_to_add:
            print("No items to add (all items have quantity 0)")
            return False
        
        # If order is paid, create a NEW order entry (preserve existing paid items)
        if is_paid or is_post_payment:
            # Generate new order ID for the additional items
            new_order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            new_order_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Calculate totals for new order (with admin fee)
            total_usd = sum(item.get('line_total_usd', 0) for item in items_to_add)
            total_php = sum(item.get('line_total_php', 0) for item in items_to_add)
            grand_total_php = total_php + ADMIN_FEE_PHP
            
            # Find the last row of the existing order to insert after it
            last_order_row = first_order_row
            for row_num, row in enumerate(all_values[1:], start=2):
                if len(row) > col_indices['order_id'] and row[col_indices['order_id']] == order_id:
                    last_order_row = row_num
            
            # Insert position is after the last row of existing order
            insert_row = last_order_row + 1
            
            # Create new first row for the additional order
            new_first_row = [
                new_order_id,                        # Column A: New Order ID
                new_order_date,                      # Column B: New Order Date
                order_info['full_name'],            # Column C: Name (same customer)
                order_info['telegram'],             # Column D: Telegram Username (same)
                '',                                  # Column E: Supplier - EMPTY (no product in first row)
                '',                                  # Column F: Product Code - EMPTY (no product in first row)
                '',                                  # Column G: Product Name - EMPTY
                '',                                  # Column H: Order Type - EMPTY
                '',                                  # Column I: QTY - EMPTY
                '',                                  # Column J: Unit Price USD - EMPTY
                '',                                  # Column K: Line Total USD - EMPTY
                exchange_rate,                       # Column L: Exchange Rate
                '',                                  # Column M: Line Total PHP - EMPTY
                ADMIN_FEE_PHP,                      # Column N: Admin Fee PHP (separate admin fee for new items)
                grand_total_php,                    # Column O: Grand Total PHP (only on first row)
                'Pending',                          # Column P: Order Status - Pending (unpaid)
                'No',                               # Column Q: Locked - No
                'Unpaid',                           # Column R: Payment Status - Unpaid
                f'Additional items for {order_id}', # Column S: Remarks - link to original order
                '',                                 # Column T: Link to Payment
                '',                                 # Column U: Payment Date
                '',                                 # Column V: Full Name (duplicate)
                order_info['contact_number'],        # Column W: Contact Number
                order_info['mailing_address'],       # Column X: Mailing Address
                ''                                  # Column Y: Tracking Number
            ]
            
            # Insert the new first row
            worksheet.insert_rows([new_first_row], insert_row)
            insert_row += 1
            
            # Add all new items as separate rows below the new first row
            rows_to_add = []
            for item in items_to_add:
                row = [
                    new_order_id,                    # Column A: New Order ID
                    new_order_date,                   # Column B: New Order Date
                    order_info['full_name'],          # Column C: All rows have Name
                    order_info['telegram'],           # Column D: All rows have Telegram
                    item.get('supplier', ''),         # Column E: Supplier
                    item['product_code'],             # Column F: Product Code
                    item.get('product_name', ''),     # Column G: Product Name
                    item['order_type'],               # Column H: Order Type
                    item['qty'],                     # Column I: QTY
                    item.get('unit_price_usd', 0),   # Column J: Unit Price USD
                    item.get('line_total_usd', 0),    # Column K: Line Total USD
                    exchange_rate,                    # Column L: Exchange Rate
                    item.get('line_total_php', 0),    # Column M: Line Total PHP
                    '',                               # Column N: Admin Fee - only on first row
                    '',                               # Column O: Grand Total - only on first row
                    '',                               # Column P: Order Status - only on first row
                    '',                               # Column Q: Locked - only on first row
                    '',                               # Column R: Payment Status - only on first row
                    f'Additional items for {order_id}', # Column S: Remarks
                    '',                               # Column T: Link to Payment
                    '',                               # Column U: Payment Date
                    '',                               # Column V: Full Name (duplicate)
                    '',                               # Column W: Contact Number
                    '',                               # Column X: Mailing Address
                    ''                                # Column Y: Tracking Number
                ]
                rows_to_add.append(row)
            
            # Insert rows
            worksheet.insert_rows(rows_to_add, insert_row)
            
            print(f"✅ Created new order {new_order_id} for additional items (original order {order_id} preserved)")
            
        else:
            # Order is unpaid - REPLACE all items (not add to existing)
            # Find ALL rows for this order so we can delete them
            all_order_rows = []
            for row_num, row in enumerate(all_values[1:], start=2):
                if len(row) > col_indices['order_id'] and row[col_indices['order_id']] == order_id:
                    all_order_rows.append(row_num)
            
            # CRITICAL FIX: Use only new items - they represent the complete order state
            # The frontend sends ALL items with current quantities (not deltas)
            # So we should REPLACE existing items, not add to them
            # This fixes the bug where updating 10 kits to 2 kits resulted in 12 kits (10+2)
            final_items = [item for item in items_to_add if item.get('qty', 0) > 0]
            
            # Delete ALL rows for this order
            if all_order_rows:
                all_order_rows.sort(reverse=True)
                for row_num in all_order_rows:
                    worksheet.delete_rows(row_num)
                insert_row = first_order_row
            else:
                insert_row = first_order_row
            
            # Calculate new totals
            total_usd = sum(item.get('line_total_usd', 0) for item in final_items)
            total_php = sum(item.get('line_total_php', 0) for item in final_items)
            grand_total_php = total_php + order_info['admin_fee']
            
            # Create new first row
            first_row = [
                order_id,                           # Column A: Order ID
                order_info['order_date'],           # Column B: Order Date
                order_info['full_name'],            # Column C: Name
                order_info['telegram'],             # Column D: Telegram Username
                '',                                  # Column E: Supplier - EMPTY (no product in first row)
                '',                                  # Column F: Product Code - EMPTY
                '',                                  # Column G: Product Name - EMPTY
                '',                                  # Column H: Order Type - EMPTY
                '',                                  # Column I: QTY - EMPTY
                '',                                  # Column J: Unit Price USD - EMPTY
                '',                                  # Column K: Line Total USD - EMPTY
                exchange_rate,                       # Column L: Exchange Rate
                '',                                  # Column M: Line Total PHP - EMPTY
                order_info['admin_fee'],            # Column N: Admin Fee PHP
                grand_total_php,                     # Column O: Grand Total PHP
                order_info['order_status'],          # Column P: Order Status
                order_info['locked'],                # Column Q: Locked
                order_info['payment_status'],        # Column R: Payment Status
                '',                                  # Column S: Remarks
                order_info['payment_screenshot'],    # Column T: Link to Payment
                order_info['payment_date'],          # Column U: Payment Date
                '',                                  # Column V: Full Name (duplicate)
                order_info['contact_number'],        # Column W: Contact Number
                order_info['mailing_address'],       # Column X: Mailing Address
                ''                                   # Column Y: Tracking Number
            ]
            
            # Insert the new first row
            worksheet.insert_rows([first_row], insert_row)
            insert_row += 1
            
            # Add all items as separate rows
            if final_items:
                rows_to_add = []
                for item in final_items:
                    row = [
                        order_id,                    # Column A: Order ID
                        order_info['order_date'],    # Column B: Order Date
                        order_info['full_name'],     # Column C: Name
                        order_info['telegram'],      # Column D: Telegram
                        item.get('supplier', ''),    # Column E: Supplier
                        item['product_code'],        # Column F: Product Code
                        item.get('product_name', ''), # Column G: Product Name
                        item.get('order_type', 'Vial'), # Column H: Order Type
                        item['qty'],                 # Column I: QTY
                        item.get('unit_price_usd', 0), # Column J: Unit Price USD
                        item.get('line_total_usd', 0), # Column K: Line Total USD
                        exchange_rate,                # Column L: Exchange Rate
                        item.get('line_total_php', 0), # Column M: Line Total PHP
                        '',                          # Column N: Admin Fee - only on first row
                        '',                          # Column O: Grand Total - only on first row
                        '',                          # Column P: Order Status - only on first row
                        '',                          # Column Q: Locked - only on first row
                        '',                          # Column R: Payment Status - only on first row
                        f'Updated {order_id}',       # Column S: Remarks
                        '',                          # Column T: Link to Payment
                        '',                          # Column U: Payment Date
                        '',                          # Column V: Full Name (duplicate)
                        '',                          # Column W: Contact Number
                        '',                          # Column X: Mailing Address
                        ''                           # Column Y: Tracking Number
                    ]
                    rows_to_add.append(row)
                
                worksheet.insert_rows(rows_to_add, insert_row)
            
            print(f"✅ Updated order {order_id} with {len(final_items)} items")
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        return True
    except Exception as e:
        print(f"Error adding items: {e}")
        import traceback
        traceback.print_exc()
        return False

def recalculate_order_total(order_id, is_post_payment_addition=False):
    """Recalculate order total after adding items - sums all product line totals + admin fee
    For post-payment additions, calculates original total + additional items (without admin fee)
    """
    order = get_order_by_id(order_id)
    if not order:
        return
    
    # Get all order rows from sheet to identify post-payment items
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            worksheet = get_pephaul_worksheet(spreadsheet)
            if not worksheet:
                return False
            all_values = worksheet.get_all_values()
            headers = all_values[0] if all_values else []
            
            order_id_col = headers.index('Order ID') if 'Order ID' in headers else 0
            remarks_col = headers.index('Remarks') if 'Remarks' in headers else 16
            line_total_php_col = headers.index('Line Total PHP') if 'Line Total PHP' in headers else 11
            payment_status_col = headers.index('Payment Status') if 'Payment Status' in headers else 16
            grand_total_col = headers.index('Grand Total PHP') if 'Grand Total PHP' in headers else 14
            
            # Find first row to get original payment status and totals
            first_row_payment_status = None
            original_items_total_php = 0
            additional_items_total_php = 0
            original_admin_fee = ADMIN_FEE_PHP
            
            for row_num, row in enumerate(all_values[1:], start=2):
                if len(row) > order_id_col and row[order_id_col] == order_id:
                    if first_row_payment_status is None:
                        # First row - get payment status
                        first_row_payment_status = row[payment_status_col] if len(row) > payment_status_col else 'Unpaid'
                        # Get admin fee from first row
                        admin_fee_col = headers.index('Admin Fee PHP') if 'Admin Fee PHP' in headers else 12
                        if len(row) > admin_fee_col and row[admin_fee_col]:
                            try:
                                original_admin_fee = float(row[admin_fee_col])
                            except:
                                pass
                    else:
                        # Check if this is a post-payment item
                        remarks = row[remarks_col] if len(row) > remarks_col else ''
                        is_post_payment_item = 'Added after payment' in remarks or 'after payment' in remarks.lower()
                        
                        if len(row) > line_total_php_col:
                            try:
                                item_total = float(row[line_total_php_col]) if row[line_total_php_col] else 0
                                if is_post_payment_item:
                                    additional_items_total_php += item_total
                                else:
                                    original_items_total_php += item_total
                            except:
                                pass
            
            # Calculate totals
            # If order was paid and we're adding post-payment items, don't add admin fee to additional items
            if is_post_payment_addition and first_row_payment_status and first_row_payment_status.lower() == 'paid':
                # Calculate: original items + admin fee + additional items (no admin fee on additions)
                grand_total = original_items_total_php + original_admin_fee + additional_items_total_php
                print(f"Recalculated order {order_id} (post-payment): Original items ₱{original_items_total_php:.2f} + Admin Fee ₱{original_admin_fee:.2f} + Additional items ₱{additional_items_total_php:.2f} (no admin fee) = Grand Total ₱{grand_total:.2f}")
            else:
                # Normal recalculation - sum all items + admin fee
                total_usd = sum(item.get('line_total_usd', 0) for item in order.get('items', []) if item.get('qty', 0) > 0)
                total_php = sum(item.get('line_total_php', 0) for item in order.get('items', []) if item.get('qty', 0) > 0)
                # If PHP total is 0 but USD is available, calculate from USD
                if total_php == 0 and total_usd > 0:
                    total_php = total_usd * order.get('exchange_rate', FALLBACK_EXCHANGE_RATE)
                grand_total = total_php + ADMIN_FEE_PHP
                print(f"Recalculated order {order_id}: Subtotal PHP {total_php:.2f} + Admin Fee {ADMIN_FEE_PHP:.2f} = Grand Total PHP {grand_total:.2f}")
            
            # Update first row with new grand total
            for row_num, row in enumerate(all_values[1:], start=2):
                if len(row) > order_id_col and row[order_id_col] == order_id:
                    # Update grand total in first row
                    worksheet.update_cell(row_num, grand_total_col + 1, grand_total)
                    break
                    
        except Exception as e:
            print(f"Error recalculating order total: {e}")
            import traceback
            traceback.print_exc()
    else:
        # Fallback calculation if sheets_client not available
        total_usd = sum(item.get('line_total_usd', 0) for item in order.get('items', []) if item.get('qty', 0) > 0)
        total_php = sum(item.get('line_total_php', 0) for item in order.get('items', []) if item.get('qty', 0) > 0)
        if total_php == 0 and total_usd > 0:
            total_php = total_usd * order.get('exchange_rate', FALLBACK_EXCHANGE_RATE)
        grand_total = total_php + ADMIN_FEE_PHP
        print(f"Recalculated order {order_id} (fallback): Subtotal PHP {total_php:.2f} + Admin Fee {ADMIN_FEE_PHP:.2f} = Grand Total PHP {grand_total:.2f}")

def upload_to_imgur(file_data, order_id):
    """Upload image to Imgur as fallback storage"""
    try:
        # Imgur Client ID for anonymous uploads (free tier)
        imgur_client_id = os.getenv('IMGUR_CLIENT_ID', 'c4a16f7f1c45c0e')  # Public anonymous ID
        
        # Clean base64 data
        if ',' in file_data:
            file_data = file_data.split(',')[1]
        
        headers = {
            'Authorization': f'Client-ID {imgur_client_id}'
        }
        
        data = {
            'image': file_data,
            'type': 'base64',
            'title': f'PepHaul Payment - {order_id}',
            'description': f'Payment screenshot for order {order_id}'
        }
        
        print(f"📤 Uploading to Imgur for order {order_id}...")
        response = requests.post('https://api.imgur.com/3/image', headers=headers, data=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            link = result['data']['link']
            print(f"✅ Imgur upload successful: {link}")
            return link
        else:
            print(f"❌ Imgur upload failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Imgur upload error: {e}")
        return None

def upload_to_drive(file_data, filename, order_id):
    """Upload payment screenshot - tries Google Drive first, then Imgur as fallback"""
    
    # Try Google Drive first if configured
    if drive_service:
        try:
            from googleapiclient.http import MediaInMemoryUpload
            
            # Use the specific PepHaul Payments folder in Google Drive
            folder_id = os.getenv('PAYMENT_DRIVE_FOLDER_ID', '1HOt6b11IWp9CIazujHJMkbyCxQSrwFgg')
            
            print(f"📤 Attempting Google Drive upload to folder: {folder_id}")
            
            # Decode base64 if needed
            clean_data = file_data
            if ',' in file_data:
                clean_data = file_data.split(',')[1]
            
            file_bytes = base64.b64decode(clean_data)
            
            # Detect mime type from data
            mime_type = 'image/jpeg'
            if clean_data.startswith('/9j/'):
                mime_type = 'image/jpeg'
            elif clean_data.startswith('iVBOR'):
                mime_type = 'image/png'
            elif clean_data.startswith('R0lGO'):
                mime_type = 'image/gif'
            
            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_filename = f'{order_id}_payment_{timestamp}.jpg'
            
            # Upload file
            file_metadata = {
                'name': safe_filename,
                'parents': [folder_id]
            }
            
            media = MediaInMemoryUpload(file_bytes, mimetype=mime_type, resumable=True)
            
            print(f"Creating file: {safe_filename}")
            
            file = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,webViewLink',
                supportsAllDrives=True
            ).execute()
            
            print(f"✅ File created with ID: {file.get('id')}")
            
            # Make file viewable by anyone with link
            try:
                drive_service.permissions().create(
                    fileId=file['id'],
                    body={'type': 'anyone', 'role': 'reader'},
                    supportsAllDrives=True
                ).execute()
                print("Permissions set successfully")
            except Exception as perm_error:
                print(f"Warning: Could not set permissions: {perm_error}")
            
            return file.get('webViewLink', f"https://drive.google.com/file/d/{file['id']}/view")
            
        except Exception as e:
            error_str = str(e)
            print(f"❌ Google Drive upload failed: {e}")
            
            # Check if it's the storage quota error
            if 'storage quota' in error_str.lower() or 'storageQuotaExceeded' in error_str:
                print("⚠️ Service Account storage quota exceeded - falling back to Imgur")
            else:
                import traceback
                traceback.print_exc()
    else:
        print("⚠️ Google Drive not configured - using Imgur fallback")
    
    # Fallback to Imgur
    print("🔄 Trying Imgur as fallback storage...")
    imgur_link = upload_to_imgur(file_data, order_id)
    
    if imgur_link:
        return imgur_link
    
    print("❌ All upload methods failed")
    return None

def _fetch_inventory_stats():
    """Internal function to fetch and calculate inventory statistics - supplier-aware"""
    try:
        orders = get_orders_from_sheets()
        if not orders:
            orders = []
        
        # Use (product_code, supplier) as key to track inventory per supplier
        product_stats = defaultdict(lambda: {'total_vials': 0, 'kit_orders': 0, 'vial_orders': 0})
        
        # Build product lookup for vials_per_kit and supplier
        products = get_products()
        product_vials_map = {p['code']: p.get('vials_per_kit', VIALS_PER_KIT) for p in products}
        
        # Build map of product_code -> supplier for products (for inferring supplier if missing)
        code_to_supplier_map = {}
        code_to_suppliers_map = defaultdict(set)
        for p in products:
            code = p['code']
            supplier = p.get('supplier', 'Default')
            code_to_suppliers_map[code].add(supplier)
            if code not in code_to_supplier_map:
                code_to_supplier_map[code] = supplier
        
        for order in orders:
            if order.get('Order Status') == 'Cancelled':
                continue
                
            product_code = order.get('Product Code', '')
            if not product_code:
                continue
            
            # Get supplier from order (column E) or infer from products
            order_supplier = order.get('Supplier', '') or order.get('supplier', '')
            if not order_supplier:
                # Infer supplier: if code is unique to one supplier, use it
                if product_code in code_to_supplier_map:
                    order_supplier = code_to_supplier_map[product_code]
                elif product_code in code_to_suppliers_map:
                    # If code exists in multiple suppliers, default to first one (usually WWB)
                    order_supplier = sorted(code_to_suppliers_map[product_code])[0]
                else:
                    order_supplier = 'Default'
            
            order_type = order.get('Order Type', 'Vial')
            qty = int(order.get('QTY', 0) or 0)
            # Skip items with 0 quantity for inventory calculations
            if qty <= 0:
                continue
            vials_per_kit = product_vials_map.get(product_code, VIALS_PER_KIT)
            
            # Use (product_code, supplier) as key
            key = (product_code, order_supplier)
            
            if order_type == 'Kit':
                product_stats[key]['total_vials'] += qty * vials_per_kit
                product_stats[key]['kit_orders'] += qty
            else:
                product_stats[key]['total_vials'] += qty
                product_stats[key]['vial_orders'] += qty
        
        # Get product locks (still keyed by product_code only for backward compatibility)
        locks = get_product_locks()
        
        inventory = {}
        for (product_code, supplier), stats in product_stats.items():
            vials_per_kit = product_vials_map.get(product_code, VIALS_PER_KIT)
            total_vials = stats['total_vials']
            kits_generated = total_vials // vials_per_kit
            remaining_vials = total_vials % vials_per_kit
            slots_to_next_kit = vials_per_kit - remaining_vials if remaining_vials > 0 else 0
            
            lock_info = locks.get(product_code, {})
            max_kits = lock_info.get('max_kits', MAX_KITS_DEFAULT)
            is_locked = lock_info.get('is_locked', False) or kits_generated >= max_kits
            
            # Store inventory keyed by (product_code, supplier)
            inventory[(product_code, supplier)] = {
                'total_vials': total_vials,
                'kits_generated': kits_generated,
                'remaining_vials': remaining_vials,
                'slots_to_next_kit': slots_to_next_kit,
                'vials_per_kit': vials_per_kit,
                'max_kits': max_kits,
                'is_locked': is_locked,
                'supplier': supplier
            }
        
        return inventory
    except Exception as e:
        print(f"Error calculating inventory stats: {e}")
        import traceback
        traceback.print_exc()
        # Return empty inventory
        return {}

def get_inventory_stats():
    """Get inventory statistics with caching"""
    return get_cached('inventory', _fetch_inventory_stats, cache_duration=300)  # 5 minutes - derived data, can cache longer

def _fetch_products_from_sheets():
    """Internal function to fetch products from Price List tab, with fallback to alternate tab"""
    if not sheets_client:
        print("⚠️ sheets_client is None - cannot fetch products from Google Sheets")
        return None
    
    try:
        print("📊 Fetching products from Google Sheets...")
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Try to find Price List worksheet first
        worksheet = None
        records = []
        tab_name = None
        
        try:
            worksheet = spreadsheet.worksheet('Price List')
            records = worksheet.get_all_records()
            tab_name = 'Price List'
            print(f"📋 Found {len(records)} records in 'Price List' tab")
        except Exception as e:
            print(f"⚠️ Could not load from 'Price List' tab: {e}")
            print("   Trying fallback tab (gid=1334586174)...")
            
            # Fallback: Try to find worksheet by gid (1334586174)
            try:
                # Get all worksheets and find by gid
                all_worksheets = spreadsheet.worksheets()
                fallback_worksheet = None
                for ws in all_worksheets:
                    if str(ws.id) == '1334586174':
                        fallback_worksheet = ws
                        break
                
                if fallback_worksheet:
                    worksheet = fallback_worksheet
                    records = worksheet.get_all_records()
                    tab_name = fallback_worksheet.title
                    print(f"✅ Found {len(records)} records in fallback tab '{tab_name}' (gid=1334586174)")
                else:
                    print(f"⚠️ Fallback tab with gid=1334586174 not found")
                    # Try to use first available worksheet as last resort
                    if all_worksheets:
                        worksheet = all_worksheets[0]
                        records = worksheet.get_all_records()
                        tab_name = worksheet.title
                        print(f"⚠️ Using first available worksheet '{tab_name}' as last resort")
            except Exception as fallback_error:
                print(f"❌ Fallback also failed: {fallback_error}")
                return None
        
        if not records or len(records) == 0:
            print(f"⚠️ No records found in '{tab_name}' tab")
            return None
        
        # Debug: Log available columns if records exist
        if records:
            print(f"📋 Available columns in '{tab_name}': {list(records[0].keys())}")
            print(f"📋 Sample record: {records[0]}")
        
        products = []
        for record in records:
            # Handle different column name variations
            code = record.get('Product Code') or record.get('Code') or record.get('code', '').strip()
            name = record.get('Product Name') or record.get('Product') or record.get('Name') or record.get('name', '').strip()
            kit_price_str = str(record.get('USD Kit Price') or record.get('Kit Price') or record.get('kit_price') or record.get('Kit', '0')).strip()
            vial_price_str = str(record.get('USD Price/Vial') or record.get('Vial Price') or record.get('vial_price') or record.get('Vial', '0')).strip()
            vials_per_kit_str = str(record.get('Vials/Kit') or record.get('Vials Per Kit') or record.get('vials_per_kit') or '10').strip()
            supplier = record.get('Supplier') or record.get('supplier') or 'Default'
            
            # Skip empty rows
            if not code or not name:
                continue
            
            # Parse prices (remove $ and commas)
            try:
                kit_price = float(kit_price_str.replace('$', '').replace(',', '').strip() or 0)
                vial_price = float(vial_price_str.replace('$', '').replace(',', '').strip() or 0)
                vials_per_kit = int(float(vials_per_kit_str.strip() or 10))
            except (ValueError, AttributeError) as parse_error:
                print(f"⚠️ Failed to parse product {code}: {parse_error}")
                continue
            
            # Skip if prices are 0
            if kit_price == 0 and vial_price == 0:
                continue
            
            # Normalize supplier and code (strip whitespace, ensure consistent format)
            normalized_supplier = str(supplier).strip() if supplier else 'Default'
            normalized_code = str(code).strip() if code else ''
            
            products.append({
                'code': normalized_code,
                'name': name,
                'kit_price': kit_price,
                'vial_price': vial_price,
                'vials_per_kit': vials_per_kit,
                'supplier': normalized_supplier
            })
        
        print(f"✅ Successfully loaded {len(products)} products from '{tab_name}' tab")
        
        # Debug: Show supplier breakdown
        suppliers_found = {}
        for p in products:
            supplier = p.get('supplier', 'Default')
            suppliers_found[supplier] = suppliers_found.get(supplier, 0) + 1
        
        print(f"   📊 Products by supplier: {suppliers_found}")
        
        # Verify YIWU and WWB suppliers are present
        supplier_keys_upper = [s.upper() for s in suppliers_found.keys()]
        if 'YIWU' not in supplier_keys_upper:
            print(f"   ⚠️ Warning: YIWU supplier not found in products")
        if 'WWB' not in supplier_keys_upper:
            print(f"   ⚠️ Warning: WWB supplier not found in products")
        
        # Debug: Show sample products including LEMBOT if present
        lembot_found = [p for p in products if 'LEMBOT' in str(p.get('code', '')).upper()]
        if lembot_found:
            print(f"   📦 LEMBOT products found: {[(p.get('code'), p.get('supplier'), p.get('name')) for p in lembot_found]}")
        else:
            print(f"   ⚠️ No LEMBOT products found in loaded products")
        
        return products if products else None
        
    except Exception as e:
        print(f"❌ Error reading products from sheet: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_products():
    """Get products from Google Sheet Price List tab, fallback to hardcoded list"""
    # Try to get from sheet first (with caching)
    try:
        print("🔄 Attempting to load products from Google Sheets...")
        cached_products = get_cached('products_sheet', _fetch_products_from_sheets, cache_duration=60)  # 1 minute - allow faster updates
        if cached_products and len(cached_products) > 0:
            print(f"✅ Loaded {len(cached_products)} products from Google Sheet")
            return cached_products
        else:
            print(f"⚠️ Cached products is empty or None: {cached_products}")
    except Exception as e:
        print(f"❌ Error loading products from sheet, using fallback: {e}")
        import traceback
        traceback.print_exc()
    
    # Fallback to hardcoded list
    print("⚠️ Using hardcoded product list (fallback)")
    return [
        # Tirzepatide
        {"code": "TR5", "name": "Tirzepatide - 5mg", "kit_price": 45, "vial_price": 4.5, "vials_per_kit": 10},
        {"code": "TR10", "name": "Tirzepatide - 10mg", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "TR15", "name": "Tirzepatide - 15mg", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "TR20", "name": "Tirzepatide - 20mg", "kit_price": 85, "vial_price": 8.5, "vials_per_kit": 10},
        {"code": "TR30", "name": "Tirzepatide - 30mg", "kit_price": 105, "vial_price": 10.5, "vials_per_kit": 10},
        {"code": "TR40", "name": "Tirzepatide - 40mg", "kit_price": 130, "vial_price": 13.0, "vials_per_kit": 10},
        {"code": "TR50", "name": "Tirzepatide - 50mg", "kit_price": 155, "vial_price": 15.5, "vials_per_kit": 10},
        {"code": "TR60", "name": "Tirzepatide - 60mg", "kit_price": 180, "vial_price": 18.0, "vials_per_kit": 10},
        {"code": "TR100", "name": "Tirzepatide - 100mg", "kit_price": 285, "vial_price": 28.5, "vials_per_kit": 10},
        # Semaglutide
        {"code": "SM2", "name": "Semaglutide - 2mg", "kit_price": 35, "vial_price": 3.5, "vials_per_kit": 10},
        {"code": "SM5", "name": "Semaglutide - 5mg", "kit_price": 45, "vial_price": 4.5, "vials_per_kit": 10},
        {"code": "SM10", "name": "Semaglutide - 10mg", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "SM15", "name": "Semaglutide - 15mg", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "SM20", "name": "Semaglutide - 20mg", "kit_price": 85, "vial_price": 8.5, "vials_per_kit": 10},
        {"code": "SM30", "name": "Semaglutide - 30mg", "kit_price": 105, "vial_price": 10.5, "vials_per_kit": 10},
        # Retatrutide
        {"code": "RT5", "name": "Retatrutide - 5mg", "kit_price": 70, "vial_price": 7.0, "vials_per_kit": 10},
        {"code": "RT10", "name": "Retatrutide - 10mg", "kit_price": 100, "vial_price": 10.0, "vials_per_kit": 10},
        {"code": "RT15", "name": "Retatrutide - 15mg", "kit_price": 125, "vial_price": 12.5, "vials_per_kit": 10},
        {"code": "RT20", "name": "Retatrutide - 20mg", "kit_price": 150, "vial_price": 15.0, "vials_per_kit": 10},
        {"code": "RT30", "name": "Retatrutide - 30mg", "kit_price": 190, "vial_price": 19.0, "vials_per_kit": 10},
        {"code": "RT40", "name": "Retatrutide - 40mg", "kit_price": 235, "vial_price": 23.5, "vials_per_kit": 10},
        {"code": "RT50", "name": "Retatrutide - 50mg", "kit_price": 275, "vial_price": 27.5, "vials_per_kit": 10},
        {"code": "RT60", "name": "Retatrutide - 60mg", "kit_price": 315, "vial_price": 31.5, "vials_per_kit": 10},
        # TB-500
        {"code": "BT5", "name": "TB-500 - 5mg", "kit_price": 70, "vial_price": 7.0, "vials_per_kit": 10},
        {"code": "BT10", "name": "TB-500 - 10mg", "kit_price": 130, "vial_price": 13.0, "vials_per_kit": 10},
        {"code": "BT20", "name": "TB-500 - 20mg", "kit_price": 185, "vial_price": 18.5, "vials_per_kit": 10},
        {"code": "B10F", "name": "TB-500 Fragment - 10mg", "kit_price": 90, "vial_price": 9.0, "vials_per_kit": 10},
        # BPC-157
        {"code": "BC5", "name": "BPC-157 - 5mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "BC10", "name": "BPC-157 - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "BC20", "name": "BPC-157 - 20mg", "kit_price": 100, "vial_price": 10.0, "vials_per_kit": 10},
        # AOD9604
        {"code": "2AD", "name": "AOD9604 - 2mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        {"code": "5AD", "name": "AOD9604 - 5mg", "kit_price": 90, "vial_price": 9.0, "vials_per_kit": 10},
        {"code": "10AD", "name": "AOD9604 - 10mg", "kit_price": 155, "vial_price": 15.5, "vials_per_kit": 10},
        # Blends
        {"code": "BB10", "name": "BPC 5mg + TB500 5mg - 10mg", "kit_price": 90, "vial_price": 9.0, "vials_per_kit": 10},
        {"code": "BB20", "name": "BPC 10mg + TB500 10mg - 20mg", "kit_price": 155, "vial_price": 15.5, "vials_per_kit": 10},
        {"code": "BBG50", "name": "GHK-Cu + TB500 + BPC157 - 50mg", "kit_price": 155, "vial_price": 15.5, "vials_per_kit": 10},
        {"code": "BBG70", "name": "GHK-Cu + TB500 + BPC157 - 70mg", "kit_price": 175, "vial_price": 17.5, "vials_per_kit": 10},
        {"code": "KLOW", "name": "GHK-Cu + TB500 + BPC157 + KPV - 80mg", "kit_price": 195, "vial_price": 19.5, "vials_per_kit": 10},
        {"code": "Ti17", "name": "Tesamorelin + Ipamorelin - 17mg", "kit_price": 170, "vial_price": 17.0, "vials_per_kit": 10},
        {"code": "CS10", "name": "Cagrilintide + Semaglutide - 10mg", "kit_price": 125, "vial_price": 12.5, "vials_per_kit": 10},
        {"code": "RC10", "name": "Retatrutide + Cagrilintide - 10mg", "kit_price": 160, "vial_price": 16.0, "vials_per_kit": 10},
        {"code": "XS20", "name": "Selank + Semax - 20mg", "kit_price": 95, "vial_price": 9.5, "vials_per_kit": 10},
        {"code": "NM120", "name": "NAD+ + Mots-C + 5-Amino-1MQ - 120mg", "kit_price": 145, "vial_price": 14.5, "vials_per_kit": 10},
        # CJC-1295
        {"code": "CP10", "name": "CJC-1295 (no DAC) + Ipamorelin - 10mg", "kit_price": 95, "vial_price": 9.5, "vials_per_kit": 10},
        {"code": "CND5", "name": "CJC-1295 no DAC - 5mg", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "CND10", "name": "CJC-1295 no DAC - 10mg", "kit_price": 120, "vial_price": 12.0, "vials_per_kit": 10},
        {"code": "CD2", "name": "CJC-1295 With DAC - 2mg", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "CD5", "name": "CJC-1295 With DAC - 5mg", "kit_price": 135, "vial_price": 13.5, "vials_per_kit": 10},
        {"code": "CD10", "name": "CJC-1295 With DAC - 10mg", "kit_price": 245, "vial_price": 24.5, "vials_per_kit": 10},
        # Cagrilintide
        {"code": "CGL5", "name": "Cagrilintide - 5mg", "kit_price": 80, "vial_price": 8.0, "vials_per_kit": 10},
        {"code": "CGL10", "name": "Cagrilintide - 10mg", "kit_price": 130, "vial_price": 13.0, "vials_per_kit": 10},
        {"code": "CGL20", "name": "Cagrilintide - 20mg", "kit_price": 235, "vial_price": 23.5, "vials_per_kit": 10},
        # DSIP
        {"code": "DS5", "name": "DSIP - 5mg", "kit_price": 45, "vial_price": 4.5, "vials_per_kit": 10},
        {"code": "DS10", "name": "DSIP - 10mg", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "DS15", "name": "DSIP - 15mg", "kit_price": 85, "vial_price": 8.5, "vials_per_kit": 10},
        # Others
        {"code": "DR5", "name": "Dermorphin - 5mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "ET10", "name": "Epithalon - 10mg", "kit_price": 45, "vial_price": 4.5, "vials_per_kit": 10},
        {"code": "ET40", "name": "Epithalon - 40mg", "kit_price": 140, "vial_price": 14.0, "vials_per_kit": 10},
        {"code": "ET50", "name": "Epithalon - 50mg", "kit_price": 155, "vial_price": 15.5, "vials_per_kit": 10},
        {"code": "E3K", "name": "EPO - 3000IU", "kit_price": 100, "vial_price": 20.0, "vials_per_kit": 5},
        {"code": "F410", "name": "FOXO4 - 10mg", "kit_price": 320, "vial_price": 32.0, "vials_per_kit": 10},
        {"code": "AU100", "name": "AHK-CU - 100mg", "kit_price": 70, "vial_price": 7.0, "vials_per_kit": 10},
        {"code": "CU50", "name": "GHK-CU - 50mg", "kit_price": 35, "vial_price": 3.5, "vials_per_kit": 10},
        {"code": "CU100", "name": "GHK-CU - 100mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        # GHRP
        {"code": "G25", "name": "GHRP-2 - 5mg", "kit_price": 35, "vial_price": 3.5, "vials_per_kit": 10},
        {"code": "G210", "name": "GHRP-2 - 10mg", "kit_price": 55, "vial_price": 5.5, "vials_per_kit": 10},
        {"code": "G65", "name": "GHRP-6 - 5mg", "kit_price": 35, "vial_price": 3.5, "vials_per_kit": 10},
        {"code": "G610", "name": "GHRP-6 - 10mg", "kit_price": 55, "vial_price": 5.5, "vials_per_kit": 10},
        {"code": "GTT", "name": "Glutathione - 1500mg", "kit_price": 90, "vial_price": 9.0, "vials_per_kit": 10},
        {"code": "GND2", "name": "Gonadorelin - 2mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        # HGH
        {"code": "H06", "name": "HGH 191AA - 6iu", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        {"code": "H10", "name": "HGH 191AA - 10iu", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "H12", "name": "HGH 191AA - 12iu", "kit_price": 70, "vial_price": 7.0, "vials_per_kit": 10},
        {"code": "H15", "name": "HGH 191AA - 15iu", "kit_price": 80, "vial_price": 8.0, "vials_per_kit": 10},
        {"code": "H24", "name": "HGH 191AA - 24iu", "kit_price": 105, "vial_price": 10.5, "vials_per_kit": 10},
        {"code": "H36", "name": "HGH 191AA - 36iu", "kit_price": 145, "vial_price": 14.5, "vials_per_kit": 10},
        {"code": "GH100", "name": "HGH 191AA - 100iu", "kit_price": 370, "vial_price": 37.0, "vials_per_kit": 10},
        {"code": "HU10", "name": "Humanin - 10mg", "kit_price": 185, "vial_price": 18.5, "vials_per_kit": 10},
        {"code": "G75", "name": "HMG - 75IU", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "HX2", "name": "Hexarelin - 2mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "HX5", "name": "Hexarelin - 5mg", "kit_price": 80, "vial_price": 8.0, "vials_per_kit": 10},
        {"code": "G5K", "name": "HCG - 5000IU", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "G10K", "name": "HCG - 10000IU", "kit_price": 135, "vial_price": 13.5, "vials_per_kit": 10},
        {"code": "FR2", "name": "HGH Fragment 176-191 - 2mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        {"code": "FR5", "name": "HGH Fragment 176-191 - 5mg", "kit_price": 90, "vial_price": 9.0, "vials_per_kit": 10},
        {"code": "HA5", "name": "Hyaluronic Acid - 5mg", "kit_price": 35, "vial_price": 3.5, "vials_per_kit": 10},
        # Ipamorelin
        {"code": "IP5", "name": "Ipamorelin - 5mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "IP10", "name": "Ipamorelin - 10mg", "kit_price": 70, "vial_price": 7.0, "vials_per_kit": 10},
        # IGF
        {"code": "IG01", "name": "IGF-1 LR3 - 0.1mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "IG1", "name": "IGF-1 LR3 - 1mg", "kit_price": 185, "vial_price": 18.5, "vials_per_kit": 10},
        # KissPeptin
        {"code": "KS5", "name": "KissPeptin-10 - 5mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        {"code": "KS10", "name": "KissPeptin-10 - 10mg", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "KP10", "name": "KPV - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "375", "name": "LL37 - 5mg", "kit_price": 95, "vial_price": 9.5, "vials_per_kit": 10},
        # MT
        {"code": "MT1", "name": "MT-1 - 10mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        {"code": "ML10", "name": "MT-2 - 10mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        # MOTS-C
        {"code": "MS10", "name": "MOTS-C - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "MS40", "name": "MOTS-C - 40mg", "kit_price": 175, "vial_price": 17.5, "vials_per_kit": 10},
        {"code": "FM2", "name": "MGF - 2mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        # Mazdutide
        {"code": "MDT5", "name": "Mazdutide - 5mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "MDT10", "name": "Mazdutide - 10mg", "kit_price": 190, "vial_price": 19.0, "vials_per_kit": 10},
        # NAD+
        {"code": "NJ3100", "name": "NAD+ - 100mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "NJ500", "name": "NAD+ - 500mg", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "NJ1000", "name": "NAD+ - 1000mg", "kit_price": 125, "vial_price": 12.5, "vials_per_kit": 10},
        # Oxytocin
        {"code": "OT2", "name": "Oxytocin Acetate - 2mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "OT5", "name": "Oxytocin Acetate - 5mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        {"code": "OT10", "name": "Oxytocin Acetate - 10mg", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        # P21, PE, PEG MGF
        {"code": "P210", "name": "P21 - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "PE10", "name": "PE 22-28 - 10mg", "kit_price": 50, "vial_price": 5.0, "vials_per_kit": 10},
        {"code": "FMP2", "name": "PEG MGF - 2mg", "kit_price": 80, "vial_price": 8.0, "vials_per_kit": 10},
        {"code": "P41", "name": "PT-141 - 10mg", "kit_price": 55, "vial_price": 5.5, "vials_per_kit": 10},
        # Pinealon
        {"code": "PIN5", "name": "Pinealon - 5mg", "kit_price": 45, "vial_price": 4.5, "vials_per_kit": 10},
        {"code": "PIN10", "name": "Pinealon - 10mg", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "PIN20", "name": "Pinealon - 20mg", "kit_price": 95, "vial_price": 9.5, "vials_per_kit": 10},
        # PNC-27
        {"code": "PN5", "name": "PNC-27 - 5mg", "kit_price": 90, "vial_price": 9.0, "vials_per_kit": 10},
        {"code": "PN10", "name": "PNC-27 - 10mg", "kit_price": 155, "vial_price": 15.5, "vials_per_kit": 10},
        # Survodutide
        {"code": "SUR10", "name": "Survodutide - 10mg", "kit_price": 215, "vial_price": 21.5, "vials_per_kit": 10},
        # SNAP-8
        {"code": "NP810", "name": "SNAP-8 - 10mg", "kit_price": 45, "vial_price": 4.5, "vials_per_kit": 10},
        # SS-31
        {"code": "2S10", "name": "SS-31 - 10mg", "kit_price": 90, "vial_price": 9.0, "vials_per_kit": 10},
        {"code": "2S50", "name": "SS-31 - 50mg", "kit_price": 330, "vial_price": 33.0, "vials_per_kit": 10},
        # Selank
        {"code": "SK5", "name": "Selank - 5mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "SK10", "name": "Selank - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "SK30", "name": "Selank - 30mg", "kit_price": 125, "vial_price": 12.5, "vials_per_kit": 10},
        # Semax
        {"code": "XA5", "name": "Semax - 5mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "XA10", "name": "Semax - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "XA30", "name": "Semax - 30mg", "kit_price": 125, "vial_price": 12.5, "vials_per_kit": 10},
        # NA Selank/Semax Amidate
        {"code": "NSK30", "name": "NA Selank Amidate - 30mg", "kit_price": 135, "vial_price": 13.5, "vials_per_kit": 10},
        {"code": "NXA30", "name": "NA Semax Amidate - 30mg", "kit_price": 135, "vial_price": 13.5, "vials_per_kit": 10},
        # Sermorelin
        {"code": "SMO5", "name": "Sermorelin Acetate - 5mg", "kit_price": 70, "vial_price": 7.0, "vials_per_kit": 10},
        {"code": "SMO10", "name": "Sermorelin Acetate - 10mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        # Tesamorelin
        {"code": "TSM5", "name": "Tesamorelin - 5mg", "kit_price": 80, "vial_price": 8.0, "vials_per_kit": 10},
        {"code": "TSM10", "name": "Tesamorelin - 10mg", "kit_price": 135, "vial_price": 13.5, "vials_per_kit": 10},
        {"code": "TSM20", "name": "Tesamorelin - 20mg", "kit_price": 255, "vial_price": 25.5, "vials_per_kit": 10},
        # Thymalin
        {"code": "TY10", "name": "Thymalin - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "TA5", "name": "Thymosin Alpha-1 - 5mg", "kit_price": 80, "vial_price": 8.0, "vials_per_kit": 10},
        {"code": "TA10", "name": "Thymosin Alpha-1 - 10mg", "kit_price": 135, "vial_price": 13.5, "vials_per_kit": 10},
        # VIP
        {"code": "VP10", "name": "VIP - 10mg", "kit_price": 145, "vial_price": 14.5, "vials_per_kit": 10},
        # 5-Amino-1MQ
        {"code": "5AM", "name": "5-Amino-1MQ - 5mg", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "10AM", "name": "5-Amino-1MQ - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "50AM", "name": "5-Amino-1MQ - 50mg", "kit_price": 80, "vial_price": 8.0, "vials_per_kit": 10},
        # Adamax
        {"code": "AD5", "name": "Adamax - 5mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        # Alprostadil
        {"code": "PRO20", "name": "Alprostadil - 20MCG", "kit_price": 115, "vial_price": 23.0, "vials_per_kit": 5},
        # AICAR
        {"code": "AR50", "name": "AICAR - 50mg", "kit_price": 70, "vial_price": 7.0, "vials_per_kit": 10},
        # ACE-031
        {"code": "AE1", "name": "ACE-031 - 1mg", "kit_price": 85, "vial_price": 8.5, "vials_per_kit": 10},
        # Adipotide
        {"code": "AP2", "name": "Adipotide - 2mg", "kit_price": 70, "vial_price": 7.0, "vials_per_kit": 10},
        {"code": "AP5", "name": "Adipotide - 5mg", "kit_price": 145, "vial_price": 14.5, "vials_per_kit": 10},
        # ARA-290
        {"code": "RA10", "name": "ARA-290 - 10mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        # Botulinum Toxin
        {"code": "XT100", "name": "Botulinum Toxin - 100iu", "kit_price": 145, "vial_price": 14.5, "vials_per_kit": 10},
        # Bioregulators
        {"code": "CA20", "name": "Cardiogen - 20mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "COR20", "name": "Cortagen - 20mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "CH20", "name": "Chonluten - 20mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "LAX20", "name": "Cartalax - 20mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "OV20", "name": "Ovagen - 20mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "PA20", "name": "Pancragen - 20mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "VI20", "name": "Vilon - 20mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "TG20", "name": "Testagen - 20mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        # Water
        {"code": "AA10", "name": "AA Water - 10ml", "kit_price": 15, "vial_price": 1.5, "vials_per_kit": 10},
        {"code": "BA03", "name": "BAC Water - 3ml", "kit_price": 15, "vial_price": 1.5, "vials_per_kit": 10},
        {"code": "BA10", "name": "BAC Water - 10ml", "kit_price": 15, "vial_price": 1.5, "vials_per_kit": 10},
        # Lipo Blends
        {"code": "LC120", "name": "Lipo-C 120mg\nMethionine 15mg \ncholine Chloride 50mg \nCarnitine 50mg \nDexpanthenol 5mg", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "LC216", "name": "Lipo-B [Lipo C 216mg]\nL-Carnitine 20mg \nL-Arginine 20mg \nMethionine 25mg \nInositol 50mg \nCholine 50mg \nB6 (Pyridoxine) 25mg \nB5(Dexpanthenol) 25mg \nB12 (Methylcobalamin) 1mg", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "LC425", "name": "Lipo-C [FOCUS] \nATP 50mg \nERIA JARENSIS 50mg \nL CARNITINE 200mg \nMIC BLEND 25/50/50mg \nLICOCAINE 0.1% \nBENZYL ALCOHOL 2%", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "LC500", "name": "L-Carnitine 500mg", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "LC526", "name": "Lipo-C [FAT BLASTER] \nL CARNITINE 300mg \nMETHIONINE 25mg \nINOSITOL 50mg \nCHOLINE 50mg \nB12 1mg \nB6 50mg \nNADH 50mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "LC553", "name": "SUPER SHRED \nL-Carnitine 400mg \nMIC BLEND 100mg \nATP 50mg \nAlbuterol 2mg \nB12 1mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "RP226", "name": "Relaxation PM \nGaba 100mg \nMelatonin 1mg \nArginine 100mg \nGlutamine 25mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "SHB", "name": "SUPER Human Blend \nL-Arginine 110mg \nL-Ornithtin 110mg \nL-Citraline 120mg \nL-Lysine 70mg \nL-Glutamine 40mg \nL-Proline 60mg \nL-Taurine 60mg \nL-Carnitine 220mg\nNAC 75mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "HHB", "name": "Healthy Hair skin nails Blend \nNIACINAMIDE 50mg \nTHIAMINE HCL 50mg \nPANTOTHENIC ACID 25mg \nCHOLINE 10mg \nINOSITOL 10mg \nNIACIN 5mg \nBIOTIN 100mcg\nFOLIC ACID 100mcg\nRIBOFLAVIN 100mcg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "LMX", "name": "Lipo Mino Mix\nB6 2mg/ml\nMethionine 12.4mg/ml\nINOSITOL 25mg/ml\nCholine 25mg/ml\nB1 50mg/ml\nB2 5mg/ml\nCarnitine 125mg/ml", "kit_price": 95, "vial_price": 9.5, "vials_per_kit": 10},
        {"code": "GAZ", "name": "Immunological\nEnhancement\nGlutathione 200mg\nAscorbic Acid 200mg\nZine Sulfate 2.5mg", "kit_price": 135, "vial_price": 13.5, "vials_per_kit": 10},
        {"code": "SHR", "name": "SHRED\nL-Carnitine 200mg\nB12 250mcg\nB6 (Pyridoxine) 25mg\nInositol 50mg\nMethionine 25mg\nCholine 50mg", "kit_price": 105, "vial_price": 10.5, "vials_per_kit": 10},
        {"code": "GGH", "name": "GHK-CU 2000mcg\nGlutathione 200mg\nHistidine 100mg\nClycine 50mg\nNADH 50mg", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "SZ352", "name": "Gaba 100mg\nHistidine 100mg\nL-Theanine 50mg\nTaurine 100mg\nMelatonin 2mg\nLICOCAINE 0.2%", "kit_price": 105, "vial_price": 10.5, "vials_per_kit": 10},
        # Vitamins
        {"code": "D320", "name": "D320 (vitamins)", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "B1201", "name": "B12", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "B1210", "name": "B12", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
    ]


def get_exchange_rate():
    """Fetch live USD to PHP exchange rate"""
    try:
        response = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=5)
        if response.status_code == 200:
            return response.json()['rates'].get('PHP', FALLBACK_EXCHANGE_RATE)
    except:
        pass
    return FALLBACK_EXCHANGE_RATE

def _fetch_consolidated_order_stats():
    """Internal function to calculate consolidated order stats per supplier"""
    try:
        orders = get_orders_from_sheets()
        if not orders:
            orders = []
        
        print(f"📊 [Order Stats] Fetched {len(orders)} orders from PepHaul Entry tab")
        
        products = get_products()
        product_prices = {p['code']: {'kit_price': p['kit_price'], 'vial_price': p['vial_price']} for p in products}
        product_vials_map = {p['code']: p.get('vials_per_kit', VIALS_PER_KIT) for p in products}
        
        # Get inventory stats to calculate actual kits_generated (includes kits formed from vials)
        inventory = get_inventory_stats()
        
        # Group products by supplier
        suppliers = sorted(set([p.get('supplier', 'Default') for p in products]))
        stats_by_supplier = {}
        
        # Build a map of product_code -> supplier for products with unique codes
        # For duplicate codes, we'll use supplier from orders
        code_to_supplier_map = {}
        code_to_suppliers_map = defaultdict(set)
        for p in products:
            code = p['code']
            supplier = p.get('supplier', 'Default')
            code_to_suppliers_map[code].add(supplier)
            if code not in code_to_supplier_map:
                code_to_supplier_map[code] = supplier
        
        # Calculate stats per supplier by filtering orders
        for supplier in suppliers:
            supplier_products = [p for p in products if (p.get('supplier', 'Default') == supplier)]
            
            # Filter orders for this supplier
            supplier_orders = []
            for order in orders:
                if order.get('Order Status') == 'Cancelled':
                    continue
                order_supplier = order.get('Supplier', '') or order.get('supplier', '')
                product_code = order.get('Product Code', '')
                
                # If order has supplier, use it; otherwise infer from products
                if order_supplier:
                    if order_supplier == supplier:
                        supplier_orders.append(order)
                else:
                    # Infer supplier: if code is unique to this supplier, include it
                    if product_code in code_to_supplier_map and code_to_supplier_map[product_code] == supplier:
                        supplier_orders.append(order)
                    # If code exists in multiple suppliers, default to first one (usually WWB)
                    elif product_code in code_to_suppliers_map:
                        default_supplier = sorted(code_to_suppliers_map[product_code])[0]
                        if default_supplier == supplier:
                            supplier_orders.append(order)
            
            # Calculate inventory stats for this supplier's orders
            supplier_product_stats = defaultdict(lambda: {'total_vials': 0, 'kit_orders': 0, 'vial_orders': 0})
            for order in supplier_orders:
                product_code = order.get('Product Code', '')
                if not product_code:
                    continue
                order_type = order.get('Order Type', 'Vial')
                qty = int(order.get('QTY', 0) or 0)
                if qty <= 0:
                    continue
                vials_per_kit = product_vials_map.get(product_code, VIALS_PER_KIT)
                
                if order_type == 'Kit':
                    supplier_product_stats[product_code]['total_vials'] += qty * vials_per_kit
                    supplier_product_stats[product_code]['kit_orders'] += qty
                else:
                    supplier_product_stats[product_code]['total_vials'] += qty
                    supplier_product_stats[product_code]['vial_orders'] += qty
            
            # Calculate total completed kits value (kits_generated)
            total_completed_kits_usd = 0.0
            total_completed_kits_count = 0
            
            for product in supplier_products:
                product_code = product['code']
                if product_code in supplier_product_stats:
                    stats = supplier_product_stats[product_code]
                    vials_per_kit = product_vials_map.get(product_code, VIALS_PER_KIT)
                    kits_generated = stats['total_vials'] // vials_per_kit
                    if kits_generated > 0:
                        kit_price = product.get('kit_price', 0)
                        total_completed_kits_usd += kit_price * kits_generated
                        total_completed_kits_count += kits_generated
            
            # Calculate total incomplete kits vial value (remaining_vials that don't form complete kits)
            total_incomplete_vials_usd = 0.0
            total_incomplete_vials_count = 0
            
            for product in supplier_products:
                product_code = product['code']
                if product_code in supplier_product_stats:
                    stats = supplier_product_stats[product_code]
                    vials_per_kit = product_vials_map.get(product_code, VIALS_PER_KIT)
                    total_vials = stats['total_vials']
                    remaining_vials = total_vials % vials_per_kit
                    if remaining_vials > 0:
                        vial_price = product.get('vial_price', 0)
                        total_incomplete_vials_usd += vial_price * remaining_vials
                        total_incomplete_vials_count += remaining_vials
            
            # Combined total (completed kits + incomplete vials)
            combined_total_usd = total_completed_kits_usd + total_incomplete_vials_usd
            
            stats_by_supplier[supplier] = {
                'total_completed_kits_usd': total_completed_kits_usd,
                'total_incomplete_vials_usd': total_incomplete_vials_usd,
                'total_completed_kits_count': total_completed_kits_count,
                'total_incomplete_vials_count': total_incomplete_vials_count,
                'combined_total_usd': combined_total_usd
            }
            print(f"📊 [Order Stats] {supplier}: {len(supplier_orders)} orders, ${total_completed_kits_usd:.2f} completed kits, ${total_incomplete_vials_usd:.2f} incomplete vials")
        
        # Also calculate overall totals for backward compatibility
        total_completed_kits_usd = sum(s['total_completed_kits_usd'] for s in stats_by_supplier.values())
        total_incomplete_vials_usd = sum(s['total_incomplete_vials_usd'] for s in stats_by_supplier.values())
        total_completed_kits_count = sum(s['total_completed_kits_count'] for s in stats_by_supplier.values())
        total_incomplete_vials_count = sum(s['total_incomplete_vials_count'] for s in stats_by_supplier.values())
        
        print(f"📊 [Order Stats] Overall totals: ${total_completed_kits_usd:.2f} completed kits, ${total_incomplete_vials_usd:.2f} incomplete vials")
        
        return {
            'by_supplier': stats_by_supplier,
            'total_completed_kits_usd': total_completed_kits_usd,
            'total_incomplete_vials_usd': total_incomplete_vials_usd,
            'total_completed_kits_count': total_completed_kits_count,
            'total_incomplete_vials_count': total_incomplete_vials_count,
            'combined_total_usd': total_completed_kits_usd + total_incomplete_vials_usd,
            # Legacy fields for backward compatibility
            'total_kits_usd': total_completed_kits_usd,
            'total_vials_usd': total_incomplete_vials_usd,
            'total_kits_count': total_completed_kits_count,
            'total_vials_count': total_incomplete_vials_count
        }
    except Exception as e:
        print(f"Error calculating order stats: {e}")
        import traceback
        traceback.print_exc()
        # Return default stats - safely get suppliers
        try:
            products = get_products()
            suppliers = sorted(set([p.get('supplier', 'Default') for p in products])) if products else ['Default']
        except Exception:
            suppliers = ['Default']
        
        return {
            'by_supplier': {s: {
                'total_completed_kits_usd': 0.0,
                'total_incomplete_vials_usd': 0.0,
                'total_completed_kits_count': 0,
                'total_incomplete_vials_count': 0,
                'combined_total_usd': 0.0
            } for s in suppliers},
            'total_completed_kits_usd': 0.0,
            'total_incomplete_vials_usd': 0.0,
            'total_completed_kits_count': 0,
            'total_incomplete_vials_count': 0,
            'combined_total_usd': 0.0,
            'total_kits_usd': 0.0,
            'total_vials_usd': 0.0,
            'total_kits_count': 0,
            'total_vials_count': 0
        }

def get_consolidated_order_stats():
    """Get consolidated order stats with caching"""
    # Use shorter cache duration to ensure stats reflect current PepHaul Entry tab
    return get_cached('order_stats', _fetch_consolidated_order_stats, cache_duration=180)  # 3 minutes - match orders cache duration

# Routes
@app.route('/')
def index():
    """Main order form page"""
    try:
        exchange_rate = get_exchange_rate()
        products = get_products()
        inventory = get_inventory_stats()
        order_form_lock = get_order_form_lock()
        order_stats = get_consolidated_order_stats()
        
        # Filter products with orders for the summary section
        products_with_orders = []
        for product in products:
            product_code = product['code']
            supplier = product.get('supplier', 'Default')
            # Look up inventory using (product_code, supplier) key
            stats = inventory.get((product_code, supplier), {
                'total_vials': 0, 'kits_generated': 0, 'remaining_vials': 0,
                'slots_to_next_kit': VIALS_PER_KIT, 'max_kits': MAX_KITS_DEFAULT, 'is_locked': False,
                'vials_per_kit': VIALS_PER_KIT
            })
            product['inventory'] = stats
            if stats.get('total_vials', 0) > 0:
                products_with_orders.append(product)
        
        # Sort products: Complete kits first (by # of kits, descending), then others by proximity
        def sort_key(product):
            stats = product['inventory']
            total_vials = stats.get('total_vials', 0)
            kits_generated = stats.get('kits_generated', 0)
            slots = stats.get('slots_to_next_kit', VIALS_PER_KIT)
            
            # Complete kits: >10 vials OR at least 1 kit ordered
            is_complete_kit = total_vials > 10 or kits_generated >= 1
            
            # Return tuple: (0 for complete kits, 1 for others), then sort value
            # Complete kits: sort by kits_generated descending (negative for descending)
            # Others: sort by slots ascending (closer to completion first)
            if is_complete_kit:
                return (0, -kits_generated)  # Negative for descending order
            else:
                return (1, slots)  # Ascending by slots
        
        products_with_orders.sort(key=sort_key)
        
        # Filter incomplete kits (products with remaining vials that don't form complete kits)
        incomplete_kits = []
        orders = get_orders_from_sheets()
        
        # Build a map of product code to telegram usernames
        product_telegram_map = {}
        for order in orders:
            product_code = order.get('Product Code', '')
            if not product_code:
                continue
            
            # Get telegram username
            telegram_value = None
            for key in order.keys():
                if 'telegram' in key.lower():
                    value = order.get(key, None)
                    if value is not None:
                        value_str = str(value).strip()
                        if value_str:
                            telegram_value = value_str.replace('@', '')
                            break
            
            # Fallback to common variations
            if telegram_value is None:
                for fallback_key in ['Telegram Username', 'telegram username', 'Telegram Username ', 'TelegramUsername']:
                    value = order.get(fallback_key, None)
                    if value is not None:
                        value_str = str(value).strip()
                        if value_str:
                            telegram_value = value_str.replace('@', '')
                            break
            
            if telegram_value:
                if product_code not in product_telegram_map:
                    product_telegram_map[product_code] = set()
                product_telegram_map[product_code].add(telegram_value)
        
        for product in products_with_orders:
            stats = product['inventory']
            total_vials = stats.get('total_vials', 0)
            if total_vials > 0:
                vials_per_kit = product.get('vials_per_kit', VIALS_PER_KIT)
                remaining_vials = total_vials % vials_per_kit
                if remaining_vials > 0:  # Has incomplete kit
                    pending_vials = vials_per_kit - remaining_vials
                    product['pending_vials'] = pending_vials
                    # Add telegram usernames for this product
                    product_code = product.get('code', '')
                    telegram_usernames = sorted(list(product_telegram_map.get(product_code, set())))
                    product['pep_haulers'] = telegram_usernames
                    incomplete_kits.append(product)
        
        # Sort incomplete kits by pending vials (ascending - least needed first)
        incomplete_kits.sort(key=lambda p: p.get('pending_vials', 10))
        
        # Group products by supplier
        products_by_supplier = {}
        products_with_orders_by_supplier = {}
        incomplete_kits_by_supplier = {}
        
        for product in products:
            supplier = product.get('supplier', 'Default')
            if supplier not in products_by_supplier:
                products_by_supplier[supplier] = []
            products_by_supplier[supplier].append(product)
        
        for product in products_with_orders:
            supplier = product.get('supplier', 'Default')
            if supplier not in products_with_orders_by_supplier:
                products_with_orders_by_supplier[supplier] = []
            products_with_orders_by_supplier[supplier].append(product)
        
        for product in incomplete_kits:
            supplier = product.get('supplier', 'Default')
            if supplier not in incomplete_kits_by_supplier:
                incomplete_kits_by_supplier[supplier] = []
            incomplete_kits_by_supplier[supplier].append(product)
        
        # Get unique suppliers - include all suppliers that have products
        # Stats banners will show for all suppliers (with 0 values if no orders)
        suppliers = sorted(set(products_by_supplier.keys())) if products_by_supplier else ['Default']
        
        # Add supplier names to product names when same product code exists for multiple suppliers
        # Also add supplier name to all YIWU-only products
        # First, find all product codes that appear in multiple suppliers
        product_code_counts = {}
        for product in products:
            code = product.get('code', '')
            if code:
                if code not in product_code_counts:
                    product_code_counts[code] = []
                product_code_counts[code].append(product.get('supplier', 'Default'))
        
        def add_supplier_to_name(product, supplier):
            """Add supplier name to product name if needed"""
            code = product.get('code', '')
            if not code:
                return
            
            # Check if this code appears in multiple suppliers
            if code in product_code_counts:
                suppliers_with_code = set(product_code_counts[code])
                # Add supplier name if: multiple suppliers have this code OR supplier is YIWU
                if len(suppliers_with_code) > 1 or supplier == 'YIWU':
                    name = product.get('name', '')
                    # Remove existing supplier suffix if present
                    if f' ({supplier})' not in name:
                        product['name'] = f"{name} ({supplier})"
        
        # Update all products
        for product in products:
            add_supplier_to_name(product, product.get('supplier', 'Default'))
        
        for product in products_with_orders:
            add_supplier_to_name(product, product.get('supplier', 'Default'))
        
        for product in incomplete_kits:
            add_supplier_to_name(product, product.get('supplier', 'Default'))
        
        # Also update products_by_supplier, products_with_orders_by_supplier, incomplete_kits_by_supplier
        for supplier in products_by_supplier:
            for product in products_by_supplier[supplier]:
                add_supplier_to_name(product, supplier)
        
        for supplier in products_with_orders_by_supplier:
            for product in products_with_orders_by_supplier[supplier]:
                add_supplier_to_name(product, supplier)
        
        for supplier in incomplete_kits_by_supplier:
            for product in incomplete_kits_by_supplier[supplier]:
                add_supplier_to_name(product, supplier)
        
        # Generate price comparison data for products available from both suppliers
        price_comparison = []
        yiwu_products = products_by_supplier.get('YIWU', [])
        wwb_products = products_by_supplier.get('WWB', [])
        
        # Create maps for quick lookup
        wwb_by_code = {p['code']: p for p in wwb_products}
        
        # Compare all YIWU products with WWB
        for yiwu_product in yiwu_products:
            product_code = yiwu_product['code']
            wwb_product = wwb_by_code.get(product_code)
            
            comparison_item = {
                'code': product_code,
                'name': yiwu_product['name'],
                'yiwu_kit_price': yiwu_product.get('kit_price', 0),
                'wwb_kit_price': wwb_product.get('kit_price', 0) if wwb_product else None,
                'available_in_wwb': wwb_product is not None
            }
            price_comparison.append(comparison_item)
        
        # Sort: Products not in WWB first (LEMBOT, then SP332, then others), then products available in both
        def sort_key(item):
            code = item['code']
            available = item['available_in_wwb']
            
            # Products not in WWB come first
            if not available:
                # LEMBOT first
                if code == 'LEMBOT':
                    return (0, 0)
                # SP332 second
                elif code == 'SP332':
                    return (0, 1)
                # Other products not in WWB
                else:
                    return (0, 2)
            # Products available in both suppliers
            else:
                return (1, code)
        
        price_comparison.sort(key=sort_key)
        
        order_goal = get_order_goal()
        current_theme = get_theme()
        
        return render_template('index.html', 
                             products=products, 
                             products_by_supplier=products_by_supplier,
                             products_with_orders=products_with_orders,
                             products_with_orders_by_supplier=products_with_orders_by_supplier,
                             incomplete_kits=incomplete_kits,
                             incomplete_kits_by_supplier=incomplete_kits_by_supplier,
                             suppliers=suppliers,
                             exchange_rate=exchange_rate,
                             admin_fee=ADMIN_FEE_PHP,
                             vials_per_kit=VIALS_PER_KIT,
                             order_form_locked=order_form_lock['is_locked'],
                             order_form_lock_message=order_form_lock['message'],
                             telegram_bot_username=TELEGRAM_BOT_USERNAME,
                             order_stats=order_stats,
                             order_goal=order_goal,
                             current_theme=current_theme,
                             price_comparison=price_comparison)
    except Exception as e:
        app.logger.error(f"Error loading index page: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500

@app.route('/admin')
def admin_panel():
    """Admin panel for managing products and orders"""
    products = get_products()
    suppliers = sorted(set([p.get('supplier', 'Default') for p in products])) if products else ['Default']
    return render_template('admin.html', suppliers=suppliers)

@app.route('/api/admin/status')
def admin_status():
    """Check status of services (for debugging)"""
    creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '')
    return jsonify({
        'sheets_configured': sheets_client is not None,
        'drive_configured': drive_service is not None,
        'google_creds_set': bool(creds_json),
        'google_creds_length': len(creds_json) if creds_json else 0,
        'telegram_bot_configured': bool(TELEGRAM_BOT_TOKEN),
        'telegram_admin_configured': bool(TELEGRAM_ADMIN_CHAT_ID),
        'payment_folder_id': os.getenv('PAYMENT_DRIVE_FOLDER_ID', '1HOt6b11IWp9CIazujHJMkbyCxQSrwFgg')
    })

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    """Admin login"""
    data = request.json
    if data.get('password') == ADMIN_PASSWORD:
        session['is_admin'] = True
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Invalid password'}), 401

@app.route('/api/admin/whoami')
def api_admin_whoami():
    """Return whether the current session is authenticated as admin (used by admin UI bootstrapping)."""
    return jsonify({'is_admin': bool(session.get('is_admin'))})

@app.route('/api/admin/debug/orders')
def api_admin_debug_orders():
    """
    Admin-only diagnostic endpoint for troubleshooting why orders are not appearing.
    Returns sheet/worksheet info plus row/record counts from multiple read methods.
    """
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401

    if not sheets_client:
        return jsonify({
            'error': 'Sheets client not initialized',
            'sheets_configured': False,
            'google_sheets_id': GOOGLE_SHEETS_ID,
        }), 500

    try:
        clear_cache('orders')
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet_titles = [ws.title for ws in spreadsheet.worksheets()]

        pep_title = 'PepHaul Entry'
        if pep_title not in worksheet_titles:
            return jsonify({
                'error': f"Worksheet '{pep_title}' not found",
                'worksheet_titles': worksheet_titles,
                'google_sheets_id': GOOGLE_SHEETS_ID,
            }), 500

        worksheet = spreadsheet.worksheet(pep_title)
        all_values = worksheet.get_all_values()
        headers = all_values[0] if all_values else []

        try:
            records = worksheet.get_all_records()
            if not isinstance(records, list):
                records = []
        except Exception as e:
            records = []
            records_error = str(e)
        else:
            records_error = None

        # Manual build (same logic as _fetch_orders_from_sheets fallback)
        manual_records = []
        if all_values and headers:
            for row in all_values[1:]:
                if len(row) < len(headers):
                    row = row + [''] * (len(headers) - len(row))
                elif len(row) > len(headers):
                    row = row[:len(headers)]
                rec = {headers[i]: (row[i] if i < len(row) and row[i] else '') for i in range(len(headers))}
                if any(str(v).strip() for v in rec.values()):
                    manual_records.append(rec)

        # Quick sample
        def _norm(s):
            return str(s or '').strip()

        sample = []
        for rec in (manual_records[:10] or records[:10]):
            # Try to locate likely columns
            oid = ''
            tg = ''
            pc = ''
            for k in rec.keys():
                kl = k.lower()
                if not oid and ('order' in kl and 'id' in kl):
                    oid = _norm(rec.get(k))
                if not tg and ('telegram' in kl):
                    tg = _norm(rec.get(k))
                if not pc and ('product' in kl and 'code' in kl):
                    pc = _norm(rec.get(k))
            sample.append({'order_id': oid, 'telegram': tg, 'product_code': pc})

        return jsonify({
            'google_sheets_id': GOOGLE_SHEETS_ID,
            'worksheet_titles': worksheet_titles,
            'worksheet_used': pep_title,
            'all_values_rows_including_header': len(all_values) if all_values else 0,
            'headers_count': len(headers) if headers else 0,
            'headers_preview': headers[:25] if headers else [],
            'get_all_records_count': len(records),
            'get_all_records_error': records_error,
            'manual_records_count': len(manual_records),
            'sample_rows': sample,
        })
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

@app.route('/api/admin/products')
def api_admin_products():
    """Get products with admin data"""
    products = get_products()
    inventory = get_inventory_stats()
    locks = get_product_locks()
    orders = get_orders_from_sheets()
    
    # Build a map of product code to telegram usernames and a per-user breakdown (vials vs kits)
    from collections import defaultdict
    product_telegram_map = defaultdict(set)
    product_telegram_breakdown = defaultdict(lambda: defaultdict(lambda: {'vials': 0, 'kits': 0}))
    for order in orders:
        product_code = order.get('Product Code', '')
        if not product_code:
            continue

        # Skip items with 0 quantity
        try:
            qty = int(float(order.get('QTY', 0) or 0))
        except Exception:
            qty = 0
        if qty <= 0:
            continue

        order_type = str(order.get('Order Type', 'Vial') or 'Vial').strip()
        
        # Get telegram username
        telegram_value = None
        for key in order.keys():
            if 'telegram' in str(key).lower():
                value = order.get(key, None)
                if value is not None:
                    value_str = str(value).strip()
                    if value_str:
                        telegram_value = value_str.replace('@', '')
                        break
        
        # Fallback to common variations
        if telegram_value is None:
            for fallback_key in ['Telegram Username', 'telegram username', 'Telegram Username ', 'TelegramUsername']:
                value = order.get(fallback_key, None)
                if value is not None:
                    value_str = str(value).strip()
                    if value_str:
                        telegram_value = value_str.replace('@', '')
                        break
        
        if telegram_value:
            product_telegram_map[product_code].add(telegram_value)
            if order_type.lower() == 'kit':
                product_telegram_breakdown[product_code][telegram_value]['kits'] += qty
            else:
                product_telegram_breakdown[product_code][telegram_value]['vials'] += qty
    
    for product in products:
        code = product['code']
        supplier = product.get('supplier', 'Default')
        # Look up inventory using (product_code, supplier) key
        inv = inventory.get((code, supplier), {'kits_generated': 0, 'total_vials': 0})
        lock = locks.get(code, {'max_kits': MAX_KITS_DEFAULT, 'is_locked': False})
        
        product['kits_generated'] = inv.get('kits_generated', 0)
        product['total_vials'] = inv.get('total_vials', 0)
        product['max_kits'] = lock.get('max_kits', MAX_KITS_DEFAULT)
        product['is_locked'] = lock.get('is_locked', False) or inv.get('kits_generated', 0) >= lock.get('max_kits', MAX_KITS_DEFAULT)
        
        telegram_usernames = sorted(list(product_telegram_map.get(code, set())))
        product['pep_haulers'] = telegram_usernames

        breakdown = []
        for username in telegram_usernames:
            stats = product_telegram_breakdown.get(code, {}).get(username, {'vials': 0, 'kits': 0})
            breakdown.append({
                'username': username,
                'vials': int(stats.get('vials', 0) or 0),
                'kits': int(stats.get('kits', 0) or 0),
            })
        breakdown.sort(key=lambda x: (-(x.get('vials', 0) + x.get('kits', 0)), x.get('username', '')))
        product['pep_hauler_breakdown'] = breakdown
    
    return jsonify(products)

@app.route('/api/admin/lock-product', methods=['POST'])
def api_lock_product():
    """Lock/unlock a product"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        product_code = data.get('product_code')
        is_locked = data.get('is_locked', True)
        max_kits = data.get('max_kits')
        
        if not product_code:
            return jsonify({'error': 'Product code is required'}), 400
        
        admin_name = session.get('admin_name', 'Admin')
        if set_product_lock(product_code, is_locked, max_kits, admin_name):
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to update product lock status. Check server logs for details.'}), 500
    except Exception as e:
        print(f"❌ Error in api_lock_product: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/admin/products/bulk-lock', methods=['POST'])
def api_bulk_lock_products():
    """Bulk lock/unlock multiple products at once - optimized for large batches"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.json or {}
        product_codes = data.get('product_codes', [])
        is_locked = data.get('is_locked', True)
        max_kits = data.get('max_kits')  # Optional: can set max_kits for all products
        
        if not product_codes or not isinstance(product_codes, list):
            return jsonify({'error': 'product_codes array is required'}), 400
        
        if len(product_codes) == 0:
            return jsonify({'error': 'No product codes provided'}), 400
        
        admin_name = session.get('admin_name', 'Admin')
        success_count = 0
        failed_count = 0
        failed_products = []
        
        print(f"🔄 Starting bulk {'lock' if is_locked else 'unlock'} for {len(product_codes)} products...")
        
        # Process products in smaller batches with delays to avoid Google Sheets API rate limits
        # Google Sheets API allows ~60 requests per minute per user, so we batch conservatively
        batch_size = 5  # Smaller batches to be safe
        import time
        
        for i in range(0, len(product_codes), batch_size):
            batch = product_codes[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(product_codes) + batch_size - 1) // batch_size
            
            print(f"  Processing batch {batch_num}/{total_batches} ({len(batch)} products)...")
            
            for product_code in batch:
                try:
                    if set_product_lock(product_code, is_locked, max_kits, admin_name):
                        success_count += 1
                    else:
                        failed_count += 1
                        failed_products.append(product_code)
                        print(f"    ❌ Failed: {product_code}")
                except Exception as e:
                    failed_count += 1
                    failed_products.append(product_code)
                    print(f"    ❌ Error locking product {product_code}: {e}")
            
            # Delay between batches to respect rate limits (except for last batch)
            if i + batch_size < len(product_codes):
                time.sleep(0.2)  # 200ms delay between batches
        
        action = 'locked' if is_locked else 'unlocked'
        print(f"✅ Bulk {action} complete: {success_count} succeeded, {failed_count} failed")
        
        result = {
            'success': True,
            'message': f'{success_count} products {action} successfully',
            'success_count': success_count,
            'failed_count': failed_count
        }
        
        if failed_products:
            result['failed_products'] = failed_products[:20]  # Limit to first 20 for response size
        
        return jsonify(result)
        
    except Exception as e:
        print(f"❌ Error in api_bulk_lock_products: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/admin/lock-order-form', methods=['POST'])
def api_lock_order_form():
    """Lock/unlock the entire order form"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    is_locked = data.get('is_locked', True)
    message = sanitize_lock_message_html(data.get('message', 'Orders are currently closed. Thank you for your patience!'))
    
    if set_order_form_lock(is_locked, message):
        return jsonify({'success': True, 'is_locked': is_locked, 'message': message})
    return jsonify({'error': 'Failed to update'}), 500

@app.route('/api/admin/order-form-status')
def api_order_form_status():
    """Get order form lock status"""
    lock_status = get_order_form_lock()
    return jsonify(lock_status)

@app.route('/api/admin/order-goal')
def api_get_order_goal():
    """Get order goal amount"""
    goal = get_order_goal()
    return jsonify({'goal': goal})

@app.route('/api/admin/order-goal', methods=['POST'])
def api_set_order_goal():
    """Set order goal amount"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    goal = data.get('goal', 1000)
    
    try:
        goal = float(goal)
        if goal <= 0:
            return jsonify({'error': 'Goal must be positive'}), 400
    except:
        return jsonify({'error': 'Invalid goal amount'}), 400
    
    if set_order_goal(goal):
        return jsonify({'success': True, 'goal': goal})
    
    return jsonify({'error': 'Failed to update goal'}), 500

@app.route('/api/admin/theme')
def api_get_theme():
    """Get current theme"""
    theme = get_theme()
    return jsonify({'theme': theme})

# Timeline Management
_timeline_entries = []

def _fetch_timeline_entries(tab_name=None):
    """Internal function to fetch timeline entries from sheets - filter by PepHaul Entry ID"""
    global _timeline_entries
    entries = []
    
    if not tab_name:
        tab_name = get_current_pephaul_tab()
    
    # Use single "Timeline" tab with PepHaul Entry ID column
    timeline_tab_name = 'Timeline'
    
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            
            try:
                worksheet = spreadsheet.worksheet(timeline_tab_name)
            except Exception as e:
                # Create Timeline sheet if doesn't exist with new column structure
                try:
                    worksheet = spreadsheet.add_worksheet(title=timeline_tab_name, rows=100, cols=5)
                    worksheet.update('A1:E1', [['ID', 'PepHaul Entry ID', 'Date', 'Time', 'Details of Transaction']])
                    return []
                except Exception as create_error:
                    print(f"Error creating Timeline sheet: {create_error}")
                    import traceback
                    traceback.print_exc()
                    return []
            
            try:
                records = worksheet.get_all_records()
            except Exception as e:
                print(f"Error reading Timeline records: {e}")
                import traceback
                traceback.print_exc()
                return []
            
            for record in records:
                # Filter by current PepHaul tab (match PepHaul Entry ID column)
                # Support both old "PepHaul Number" and new "PepHaul Entry ID" column names
                pephaul_entry_id = (
                    record.get('PepHaul Entry ID', '') or 
                    record.get('PepHaul Number', '')
                ).strip()
                
                if pephaul_entry_id == tab_name and record.get('ID') and record.get('Date'):
                    entries.append({
                        'id': str(record.get('ID', '')),
                        'pephaul_entry_id': pephaul_entry_id,
                        'date': record.get('Date', ''),
                        'time': record.get('Time', ''),
                        'details': record.get('Details of Transaction', '')
                    })
        except Exception as e:
            print(f"Error getting timeline entries: {e}")
            import traceback
            traceback.print_exc()
    
    _timeline_entries = entries
    return entries

def get_timeline_entries(tab_name=None):
    """Get timeline entries (cached) - tab-specific"""
    if not tab_name:
        tab_name = get_current_pephaul_tab()
    cache_key = f'timeline_entries_{tab_name}'
    return get_cached(cache_key, lambda: _fetch_timeline_entries(tab_name), cache_duration=300)  # 5 minutes

def _fetch_all_timeline_entries():
    """Internal function to fetch ALL timeline entries from sheets (not filtered by tab)"""
    entries = []
    
    timeline_tab_name = 'Timeline'
    
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            
            try:
                worksheet = spreadsheet.worksheet(timeline_tab_name)
            except Exception as e:
                # Create Timeline sheet if doesn't exist
                try:
                    worksheet = spreadsheet.add_worksheet(title=timeline_tab_name, rows=100, cols=5)
                    worksheet.update('A1:E1', [['ID', 'PepHaul Entry ID', 'Date', 'Time', 'Details of Transaction']])
                    return []
                except Exception as create_error:
                    print(f"Error creating Timeline sheet: {create_error}")
                    import traceback
                    traceback.print_exc()
                    return []
            
            try:
                records = worksheet.get_all_records()
            except Exception as e:
                print(f"Error reading Timeline records: {e}")
                import traceback
                traceback.print_exc()
                return []
            
            for record in records:
                # Get PepHaul Entry ID (support both old and new column names)
                pephaul_entry_id = (
                    record.get('PepHaul Entry ID', '') or 
                    record.get('PepHaul Number', '')
                ).strip()
                
                # Include all entries (no filtering)
                if record.get('ID') and record.get('Date'):
                    entries.append({
                        'id': str(record.get('ID', '')),
                        'pephaul_entry_id': pephaul_entry_id or 'Unknown',
                        'date': record.get('Date', ''),
                        'time': record.get('Time', ''),
                        'details': record.get('Details of Transaction', '')
                    })
        except Exception as e:
            print(f"Error getting all timeline entries: {e}")
            import traceback
            traceback.print_exc()
    
    return entries

def get_all_timeline_entries():
    """Get ALL timeline entries (cached) - not filtered by tab"""
    cache_key = 'all_timeline_entries'
    return get_cached(cache_key, _fetch_all_timeline_entries, cache_duration=300)  # 5 minutes

def add_timeline_entry(date, time, details, tab_name=None):
    """Add timeline entry to sheets - single Timeline tab with PepHaul Entry ID"""
    import uuid
    
    if not tab_name:
        tab_name = get_current_pephaul_tab()
    
    # Use single "Timeline" tab
    timeline_tab_name = 'Timeline'
    
    entry_id = str(uuid.uuid4())[:8]
    
    if not sheets_client:
        print("Error: sheets_client not initialized")
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        
        try:
            worksheet = spreadsheet.worksheet(timeline_tab_name)
            # Check if headers need updating (support migration from old column name)
            headers = worksheet.row_values(1)
            if headers and len(headers) >= 2:
                # If old column name exists, update header row
                if 'PepHaul Number' in headers and 'PepHaul Entry ID' not in headers:
                    header_col_b = headers[1] if len(headers) > 1 else ''
                    if header_col_b == 'PepHaul Number':
                        worksheet.update('B1', [['PepHaul Entry ID']])
        except Exception as e:
            # Create Timeline sheet if doesn't exist with new column structure
            try:
                worksheet = spreadsheet.add_worksheet(title=timeline_tab_name, rows=100, cols=5)
                worksheet.update('A1:E1', [['ID', 'PepHaul Entry ID', 'Date', 'Time', 'Details of Transaction']])
            except Exception as create_error:
                print(f"Error creating Timeline sheet: {create_error}")
                import traceback
                traceback.print_exc()
                return False
        
        # Append new row with PepHaul Entry ID
        try:
            all_values = worksheet.get_all_values()
            next_row = len(all_values) + 1
            worksheet.update(f'A{next_row}:E{next_row}', [[entry_id, tab_name, date, time, details]])
            
            # Clear cache for this tab
            cache_key = f'timeline_entries_{tab_name}'
            clear_cache(cache_key)
            
            return True
        except Exception as update_error:
            print(f"Error updating Timeline sheet: {update_error}")
            import traceback
            traceback.print_exc()
            return False
    except Exception as e:
        print(f"Error adding timeline entry: {e}")
        import traceback
        traceback.print_exc()
        return False

@app.route('/api/timeline/all')
def api_get_all_timeline_entries():
    """API endpoint to get ALL timeline entries (not filtered by tab)"""
    try:
        entries = get_all_timeline_entries()
        return jsonify({
            'success': True,
            'entries': entries,
            'count': len(entries)
        })
    except Exception as e:
        print(f"Error in api_get_all_timeline_entries: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'entries': []
        }), 500

def delete_timeline_entry(entry_id, tab_name=None):
    """Delete timeline entry from sheets - single Timeline tab"""
    if not tab_name:
        tab_name = get_current_pephaul_tab()
    
    # Use single "Timeline" tab
    timeline_tab_name = 'Timeline'
    
    if not sheets_client:
        print("Error: sheets_client not initialized")
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = spreadsheet.worksheet(timeline_tab_name)
        
        # Find the row with this ID (search in first column only)
        all_values = worksheet.get_all_values()
        target_row = None
        for idx, row in enumerate(all_values[1:], start=2):
            if row and len(row) >= 1 and str(row[0]).strip() == str(entry_id).strip():
                target_row = idx
                break
        
        if target_row:
            worksheet.delete_rows(target_row)
            # Clear cache for this tab
            cache_key = f'timeline_entries_{tab_name}'
            clear_cache(cache_key)
            return True
        else:
            print(f"Timeline entry ID {entry_id} not found")
            return False
    except Exception as e:
        print(f"Error deleting timeline entry: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_timeline_entry(entry_id, date, time, details, tab_name=None):
    """Update a timeline entry in sheets - single Timeline tab"""
    if not tab_name:
        tab_name = get_current_pephaul_tab()
    
    # Use single "Timeline" tab
    timeline_tab_name = 'Timeline'
    
    if not sheets_client:
        print("Error: sheets_client not initialized")
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = spreadsheet.worksheet(timeline_tab_name)

        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) < 2:
            print("Timeline sheet is empty or has no data rows")
            return False

        # Locate ID in first column only (avoid matching in details)
        target_row = None
        for idx, row in enumerate(all_values[1:], start=2):
            if row and len(row) >= 1 and str(row[0]).strip() == str(entry_id).strip():
                target_row = idx
                break

        if not target_row:
            print(f"Timeline entry ID {entry_id} not found")
            return False

        # Update columns C, D, E (Date, Time, Details of Transaction)
        # Column B (PepHaul Entry ID) stays the same
        worksheet.update(f'C{target_row}:E{target_row}', [[date, time, details]])
        # Clear cache for this tab
        cache_key = f'timeline_entries_{tab_name}'
        clear_cache(cache_key)
        return True
    except Exception as e:
        print(f"Error updating timeline entry: {e}")
        import traceback
        traceback.print_exc()
        return False

@app.route('/api/admin/timeline')
def api_get_timeline():
    """Get timeline entries - tab-specific"""
    tab_name = request.args.get('tab_name') or get_current_pephaul_tab()
    entries = get_timeline_entries(tab_name)
    return jsonify({'entries': entries})

@app.route('/api/admin/timeline', methods=['POST'])
def api_add_timeline():
    """Add timeline entry - tab-specific"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    date = data.get('date', '')
    time = data.get('time', '')
    details = data.get('details', '')
    tab_name = data.get('tab_name') or get_current_pephaul_tab()
    
    if not date or not details:
        return jsonify({'error': 'Date and details are required'}), 400
    
    if add_timeline_entry(date, time, details, tab_name):
        return jsonify({'success': True})
    
    return jsonify({'error': 'Failed to add timeline entry'}), 500

@app.route('/api/admin/timeline/<entry_id>', methods=['DELETE'])
def api_delete_timeline(entry_id):
    """Delete timeline entry - tab-specific"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    tab_name = (request.json or {}).get('tab_name') if request.is_json else request.args.get('tab_name')
    tab_name = tab_name or get_current_pephaul_tab()
    
    if delete_timeline_entry(entry_id, tab_name):
        return jsonify({'success': True})
    
    return jsonify({'error': 'Failed to delete timeline entry'}), 500


@app.route('/api/admin/timeline/<entry_id>', methods=['PUT', 'PATCH'])
def api_update_timeline(entry_id):
    """Update timeline entry - tab-specific"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.json or {}
    date = (data.get('date') or '').strip()
    time = (data.get('time') or '').strip()
    details = (data.get('details') or '').strip()
    tab_name = data.get('tab_name') or get_current_pephaul_tab()

    if not date or not details:
        return jsonify({'error': 'Date and details are required'}), 400

    if update_timeline_entry(entry_id, date, time, details, tab_name):
        return jsonify({'success': True})

    return jsonify({'error': 'Failed to update timeline entry'}), 500

@app.route('/api/timeline')
def api_public_timeline():
    """Get timeline entries for public display - tab-specific"""
    tab_name = request.args.get('tab_name') or get_current_pephaul_tab()
    entries = get_timeline_entries(tab_name)
    return jsonify({'entries': entries})

@app.route('/api/admin/theme', methods=['POST'])
def api_set_theme():
    """Set theme"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    theme_name = data.get('theme')
    
    if not theme_name:
        return jsonify({'error': 'Theme name is required'}), 400
    
    if set_theme(theme_name):
        return jsonify({'success': True, 'theme': theme_name})
    else:
        return jsonify({'error': 'Failed to update theme'}), 500

@app.route('/api/exchange-rate')
def api_exchange_rate():
    return jsonify({'rate': get_exchange_rate(), 'currency': 'PHP'})

@app.route('/api/products')
def api_products():
    print("🎯 API /api/products called - fetching products...")
    products = get_products()
    print(f"📦 Got {len(products)} products from get_products()")
    inventory = get_inventory_stats()
    for product in products:
        product_code = product['code']
        supplier = product.get('supplier', 'Default')
        vials_per_kit = product.get('vials_per_kit', VIALS_PER_KIT)
        # Look up inventory using (product_code, supplier) key
        product['inventory'] = inventory.get((product_code, supplier), {
            'total_vials': 0, 'kits_generated': 0, 'remaining_vials': 0,
            'slots_to_next_kit': vials_per_kit, 'vials_per_kit': vials_per_kit, 'is_locked': False
        })
    return jsonify(products)

@app.route('/api/orders/lookup')
def api_orders_lookup():
    """Lookup orders by telegram - uses shorter cache for faster fetching"""
    telegram = request.args.get('telegram', '').lower().strip()
    
    if not telegram:
        return jsonify([])
    
    # Use shorter cache duration (30 seconds) for faster order lookup
    orders = get_cached('orders', _fetch_orders_from_sheets, cache_duration=30)
    
    # Normalize telegram username (remove @ if present for comparison)
    telegram_normalized = telegram.lstrip('@') if telegram else ''
    
    # Debug: Log the lookup attempt
    print(f"🔍 Looking up orders for telegram: '{telegram}' (normalized: '{telegram_normalized}')")
    print(f"📊 Total orders in cache: {len(orders)}")
    
    # Debug: Show sample of what's in the cache
    if orders and len(orders) > 0:
        print(f"📋 First order sample keys: {list(orders[0].keys())[:10]}")
        # Check if first order has Order ID
        first_order_id = orders[0].get('Order ID', None)
        print(f"📋 First order Order ID: {repr(first_order_id)}")
    
    # Group by Order ID and filter by telegram
    grouped = {}
    matched_count = 0
    checked_count = 0
    
    for order in orders:
        order_id = order.get('Order ID', '')
        if not order_id:
            continue
        
        checked_count += 1
        
        # Try multiple possible column name variations (case-insensitive, handle whitespace)
        # Also check all keys that contain 'telegram' (case-insensitive)
        order_telegram_raw = None
        telegram_key_found = None
        for key in order.keys():
            if 'telegram' in key.lower():
                value = order.get(key, '')
                # Check if value exists and is not empty (even if it's just whitespace, we want to see it)
                if value is not None:
                    value_str = str(value).strip()
                    if value_str:  # Only use if non-empty after stripping
                        order_telegram_raw = value
                        telegram_key_found = key
                        break
                    elif value_str == '' and order_telegram_raw is None:
                        # Store empty string if we haven't found anything yet (for debugging)
                        order_telegram_raw = value_str
                        telegram_key_found = key
        
        # Fallback to common variations if not found
        if order_telegram_raw is None:
            for fallback_key in ['Telegram Username', 'telegram username', 'Telegram Username ', 'TelegramUsername']:
                value = order.get(fallback_key, None)
                if value is not None:
                    value_str = str(value).strip()
                    if value_str:
                        order_telegram_raw = value
                        telegram_key_found = fallback_key
                        break
        
        # Default to empty string if still not found
        if order_telegram_raw is None:
            order_telegram_raw = ''
        
        # Convert to string and normalize
        order_telegram_str = str(order_telegram_raw) if order_telegram_raw is not None else ''
        order_telegram = order_telegram_str.lower().strip()
        order_telegram_normalized = order_telegram.lstrip('@')
        
        # Debug: Log ALL orders for troubleshooting (limit to first 10 to avoid spam)
        if checked_count <= 10:
            print(f"  [{checked_count}] Order {order_id}: key='{telegram_key_found}', raw='{repr(order_telegram_raw)}', normalized='{order_telegram_normalized}'")
            print(f"      Comparing: search='{telegram_normalized}' vs order='{order_telegram_normalized}'")
        
        # Match telegram with or without @ symbol (exact match after normalization)
        matches = False
        if telegram_normalized and order_telegram_normalized:
            # Try exact match first (case-insensitive, whitespace trimmed)
            if telegram_normalized == order_telegram_normalized:
                matches = True
                matched_count += 1
                print(f"  ✅ MATCH! Order {order_id}: '{telegram_normalized}' == '{order_telegram_normalized}'")
            # Fallback to substring match for flexibility (user input contained in order telegram)
            elif telegram_normalized in order_telegram_normalized:
                matches = True
                matched_count += 1
                print(f"  ✅ MATCH (substring)! Order {order_id}: '{telegram_normalized}' in '{order_telegram_normalized}'")
        elif checked_count <= 10:
            # Log why it didn't match (only for first 10 to avoid spam)
            if not telegram_normalized:
                print(f"      ⚠️ No match: search telegram is empty")
            elif not order_telegram_normalized:
                print(f"      ⚠️ No match: order telegram is empty")
            else:
                print(f"      ⚠️ No match: '{telegram_normalized}' != '{order_telegram_normalized}'")
        
        if not matches:
            continue
            
        if order_id not in grouped:
            # Use the dynamically found telegram value instead of hardcoded column name
            telegram_value_for_result = order_telegram_raw if order_telegram_raw else (
                order.get('Telegram Username', '') or 
                order.get('telegram username', '') or 
                ''
            )
            
            grouped[order_id] = {
                'order_id': order_id,
                'order_date': order.get('Order Date', ''),
                'full_name': order.get('Name', order.get('Full Name', '')),
                'telegram': telegram_value_for_result,
                'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                'status': order.get('Order Status', 'Pending'),
                'payment_status': order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid')),
                'payment_screenshot': order.get('Link to Payment', order.get('Payment Screenshot Link', order.get('Payment Screenshot', ''))),
                'contact_number': order.get('Contact Number', ''),
                'mailing_address': order.get('Mailing Address', ''),
                'tracking_number': order.get('Tracking Number', ''),
                'items': []
            }
        
        if order.get('Product Code'):
            qty = int(order.get('QTY', 0) or 0)
            # Only include items with quantity > 0
            if qty > 0:
                grouped[order_id]['items'].append({
                    'product_code': order.get('Product Code', ''),
                    'product_name': order.get('Product Name', ''),
                    'order_type': order.get('Order Type', 'Vial'),  # Default to 'Vial' if missing
                    'qty': qty,
                    'line_total_php': float(order.get('Line Total PHP', 0) or 0)
                })
    
    result = list(grouped.values())
    print(f"✅ Found {len(result)} matching orders for '{telegram}' ({matched_count} matches)")
    
    # If no matches found, clear cache and retry once
    if len(result) == 0 and matched_count == 0:
        print(f"⚠️ No matches found, clearing cache and retrying...")
        clear_cache('orders')
        orders = get_cached('orders', _fetch_orders_from_sheets, cache_duration=30)
        print(f"📊 Retry: Total orders after cache clear: {len(orders)}")
        
        # Retry the lookup with improved column detection
        grouped = {}
        retry_matched_count = 0
        retry_checked_count = 0
        
        for order in orders:
            order_id = order.get('Order ID', '')
            if not order_id:
                continue
            
            retry_checked_count += 1
            
            # Use same improved column lookup as main loop
            order_telegram_raw = None
            telegram_key_found = None
            for key in order.keys():
                if 'telegram' in key.lower():
                    value = order.get(key, '')
                    if value is not None:
                        value_str = str(value).strip()
                        if value_str:
                            order_telegram_raw = value
                            telegram_key_found = key
                            break
            
            if order_telegram_raw is None:
                for fallback_key in ['Telegram Username', 'telegram username', 'Telegram Username ', 'TelegramUsername']:
                    value = order.get(fallback_key, None)
                    if value is not None:
                        value_str = str(value).strip()
                        if value_str:
                            order_telegram_raw = value
                            telegram_key_found = fallback_key
                            break
            
            if order_telegram_raw is None:
                order_telegram_raw = ''
            
            order_telegram = str(order_telegram_raw).lower().strip()
            order_telegram_normalized = order_telegram.lstrip('@')
            
            if retry_checked_count <= 5:
                print(f"  [RETRY {retry_checked_count}] Order {order_id}: key='{telegram_key_found}', telegram='{order_telegram_raw}' (normalized: '{order_telegram_normalized}')")
            
            matches = False
            if telegram_normalized and order_telegram_normalized:
                if telegram_normalized == order_telegram_normalized:
                    matches = True
                    retry_matched_count += 1
                    print(f"  ✅ RETRY MATCH! Order {order_id}: '{telegram_normalized}' == '{order_telegram_normalized}'")
                elif telegram_normalized in order_telegram_normalized:
                    matches = True
                    retry_matched_count += 1
                    print(f"  ✅ RETRY MATCH (substring)! Order {order_id}: '{telegram_normalized}' in '{order_telegram_normalized}'")
            
            if not matches:
                continue
                
            if order_id not in grouped:
                telegram_value_for_result = order_telegram_raw if order_telegram_raw else (
                    order.get('Telegram Username', '') or 
                    order.get('telegram username', '') or 
                    ''
                )
                
                grouped[order_id] = {
                    'order_id': order_id,
                    'order_date': order.get('Order Date', ''),
                    'full_name': order.get('Name', order.get('Full Name', '')),
                    'telegram': telegram_value_for_result,
                    'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                    'status': order.get('Order Status', 'Pending'),
                    'payment_status': order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid')),
                    'payment_screenshot': order.get('Link to Payment', order.get('Payment Screenshot Link', order.get('Payment Screenshot', ''))),
                    'contact_number': order.get('Contact Number', ''),
                    'mailing_address': order.get('Mailing Address', ''),
                    'items': []
                }
            
            if order.get('Product Code'):
                qty = int(order.get('QTY', 0) or 0)
                if qty > 0:
                    grouped[order_id]['items'].append({
                        'product_code': order.get('Product Code', ''),
                        'product_name': order.get('Product Name', ''),
                        'order_type': order.get('Order Type', 'Vial'),
                        'qty': qty,
                        'line_total_php': float(order.get('Line Total PHP', 0) or 0)
                    })
        
        result = list(grouped.values())
        print(f"✅ Retry result: Found {len(result)} matching orders ({retry_matched_count} matches)")
    
    return jsonify(result)

@app.route('/api/orders')
def api_orders():
    """Get all orders grouped by Order ID"""
    orders = get_orders_from_sheets()
    
    # Group by Order ID
    grouped = {}
    for order in orders:
        order_id = order.get('Order ID', '')
        if not order_id:
            continue
            
        if order_id not in grouped:
            grouped[order_id] = {
                'order_id': order_id,
                'order_date': order.get('Order Date', ''),
                'full_name': order.get('Name', order.get('Full Name', '')),
                'telegram': order.get('Telegram Username', ''),
                'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                'status': order.get('Order Status', 'Pending'),
                'locked': str(order.get('Locked', 'No')).lower() == 'yes',
                'payment_status': order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid')),
                'mailing_address': order.get('Mailing Address', ''),
                'tracking_number': order.get('Tracking Number', ''),
                'items': []
            }
        
        if order.get('Product Code'):
            qty = int(order.get('QTY', 0) or 0)
            # Only include items with quantity > 0
            if qty > 0:
                grouped[order_id]['items'].append({
                    'product_code': order.get('Product Code', ''),
                    'product_name': order.get('Product Name', ''),
                    'order_type': order.get('Order Type', ''),
                    'qty': qty,
                    'line_total_php': float(order.get('Line Total PHP', 0) or 0)
                })
    
    return jsonify(list(grouped.values()))

@app.route('/api/orders/<order_id>')
def api_get_order(order_id):
    """Get specific order"""
    order = get_order_by_id(order_id)
    if order:
        return jsonify(order)
    return jsonify({'error': 'Order not found'}), 404

@app.route('/api/orders/search')
def api_search_orders():
    """Search orders by email or name"""
    query = request.args.get('q', '').lower()
    orders = get_orders_from_sheets()
    
    matching = {}
    for order in orders:
        order_id = order.get('Order ID', '')
        if not order_id:
            continue
            
        name = str(order.get('Name', order.get('Full Name', ''))).lower()
        telegram = str(order.get('Telegram Username', '')).lower()
        
        if query in name or query in telegram or query in order_id.lower():
            if order_id not in matching:
                matching[order_id] = {
                    'order_id': order_id,
                    'full_name': order.get('Name', order.get('Full Name', '')),
                    'telegram': order.get('Telegram Username', ''),
                    'status': order.get('Order Status', 'Pending'),
                    'payment_status': order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid')),
                    'grand_total_php': float(order.get('Grand Total PHP', 0) or 0)
                }
    
    return jsonify(list(matching.values()))

@app.route('/api/submit-order', methods=['POST'])
def api_submit_order():
    """Submit new order with comprehensive error handling"""
    try:
        # Validate request data
        if not request.json:
            return jsonify({
                'success': False,
                'error': 'Invalid request: No data provided'
            }), 400
        
        data = request.json
        print(f"📥 Received order submission request")
        print(f"📥 Full name: {data.get('full_name', 'MISSING')}")
        print(f"📥 Telegram: {data.get('telegram', 'MISSING')}")
        print(f"📥 Items count: {len(data.get('items', []))}")
        print(f"📥 Items: {data.get('items', [])}")
        print(f"📥 Supplier: {data.get('supplier', 'MISSING')}")
        
        # Validate required fields
        if not data.get('full_name') or not data.get('full_name').strip():
            return jsonify({
                'success': False,
                'error': 'Full name is required'
            }), 400
        
        if not data.get('items') or not isinstance(data.get('items'), list) or len(data.get('items', [])) == 0:
            return jsonify({
                'success': False,
                'error': 'At least one item is required'
            }), 400
        
        # Validate items structure
        for idx, item in enumerate(data.get('items', [])):
            if not item.get('product_code'):
                return jsonify({
                    'success': False,
                    'error': f'Item {idx + 1}: Product code is required'
                }), 400
            if not isinstance(item.get('qty'), (int, float)) or item.get('qty', 0) <= 0:
                return jsonify({
                    'success': False,
                    'error': f'Item {idx + 1}: Quantity must be a positive number'
                }), 400
        
        # Check if order form is locked
        try:
            order_form_lock = get_order_form_lock()
            if order_form_lock.get('is_locked', False):
                lock_message = order_form_lock.get('message', 'Orders are currently closed. New orders cannot be submitted at this time.')
                return jsonify({
                    'success': False,
                    'error': lock_message
                }), 403
        except Exception as e:
            print(f"⚠️ Error checking order form lock status: {e}")
            # Continue if lock check fails (fail open for availability)
        
        # Get exchange rate with error handling
        try:
            exchange_rate = get_exchange_rate()
            if not exchange_rate or exchange_rate <= 0:
                exchange_rate = FALLBACK_EXCHANGE_RATE
                print(f"⚠️ Using fallback exchange rate: {exchange_rate}")
        except Exception as e:
            print(f"⚠️ Error getting exchange rate: {e}, using fallback")
            exchange_rate = FALLBACK_EXCHANGE_RATE
        
        # Check for locked products
        try:
            inventory = get_inventory_stats()
            for item in data.get('items', []):
                code = item.get('product_code')
                supplier = item.get('supplier') or data.get('supplier') or 'Default'
                # Look up inventory using (product_code, supplier) key
                inv_entry = inventory.get((code, supplier), {})
                if inv_entry.get('is_locked'):
                    return jsonify({
                        'success': False,
                        'error': f'Product {code} is currently locked and cannot be ordered'
                    }), 400
        except Exception as e:
            print(f"⚠️ Error checking inventory: {e}")
            # Continue without inventory check if it fails
        
        # Consolidate items with same product_code + order_type + supplier
        consolidated = {}
        for item in data.get('items', []):
            # Include supplier in key to handle duplicate codes across suppliers
            # Default to 'Default' if supplier is not provided
            supplier = item.get('supplier') or data.get('supplier') or 'Default'
            key = (item['product_code'], item.get('order_type', 'Vial'), supplier)
            if key in consolidated:
                consolidated[key]['qty'] += item['qty']
            else:
                consolidated[key] = {
                    'product_code': item['product_code'],
                    'order_type': item.get('order_type', 'Vial'),
                    'supplier': supplier,
                    'qty': item['qty']
                }
        
        # Calculate totals
        total_usd = 0
        items_with_prices = []
        try:
            products = get_products()
        except Exception as e:
            print(f"❌ Error getting products: {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to load product information. Please try again.'
            }), 500
        
        for key, item in consolidated.items():
            # Validate item has product_code
            product_code_raw = item.get('product_code')
            if not product_code_raw:
                print(f"❌ Item missing product_code: {item}")
                return jsonify({
                    'success': False,
                    'error': f'Item is missing product_code. Item data: {item}'
                }), 400
            
            # Normalize product_code and supplier for comparison (strip whitespace, handle case)
            product_code = str(product_code_raw).strip()
            supplier = str(item.get('supplier', 'Default')).strip()
            print(f"🔍 Looking for product: code='{product_code}', supplier='{supplier}'")
            print(f"   Total products available: {len(products)}")
            
            # Debug: Show all products with matching code (case-insensitive)
            matching_codes_debug = [p for p in products if str(p.get('code', '')).strip().upper() == product_code.upper()]
            if matching_codes_debug:
                print(f"   Found {len(matching_codes_debug)} product(s) with code '{product_code}' (case-insensitive):")
                for p in matching_codes_debug:
                    p_code = str(p.get('code', '')).strip()
                    p_supplier = str(p.get('supplier', 'Default')).strip()
                    print(f"     - {p.get('name')} (code: '{p_code}', supplier: '{p_supplier}')")
                    print(f"       Code match: {p_code == product_code}, Supplier match: {p_supplier.lower() == supplier.lower()}")
            
            # Try to find product with matching code AND supplier (case-insensitive, trimmed)
            product = None
            for p in products:
                p_code = str(p.get('code', '')).strip()
                p_supplier = str(p.get('supplier', 'Default')).strip()
                # Case-insensitive comparison for both code and supplier
                if p_code.upper() == product_code.upper() and p_supplier.upper() == supplier.upper():
                    product = p
                    print(f"✅ Found product: {p.get('name')} (code: '{p_code}', supplier: '{p_supplier}')")
                    break
            
            # Fallback: if not found, try without supplier match (for backward compatibility)
            if not product:
                print(f"⚠️ Product '{product_code}' not found with supplier '{supplier}', trying without supplier match")
                # Show available products with this code for debugging
                matching_codes = [p for p in products if str(p.get('code', '')).strip().upper() == product_code.upper()]
                if matching_codes:
                    print(f"   Found {len(matching_codes)} product(s) with code '{product_code}':")
                    for p in matching_codes:
                        print(f"     - {p.get('name')} (supplier: '{p.get('supplier', 'Default')}')")
                product = next((p for p in products if str(p.get('code', '')).strip().upper() == product_code.upper()), None)
            
            if not product:
                print(f"❌ Product {product_code} not found in products list")
                print(f"   Searching for: code='{product_code}', supplier='{supplier}'")
                print(f"   Total products in cache: {len(products)}")
                
                # Show all LEMBOT products for debugging
                lembot_products = [p for p in products if 'LEMBOT' in str(p.get('code', '')).upper()]
                if lembot_products:
                    print(f"   Found {len(lembot_products)} LEMBOT product(s):")
                    for p in lembot_products:
                        print(f"     - Code: '{p.get('code')}', Supplier: '{p.get('supplier')}', Name: {p.get('name')}")
                
                # Show first 20 product codes for reference
                print(f"   Sample product codes: {[p.get('code') for p in products[:20]]}")
                
                return jsonify({
                    'success': False,
                    'error': f'Product {product_code} not found' + (f' for supplier {supplier}' if supplier else '')
                }), 404
            
            print(f"✅ Found product: {product.get('name', 'Unknown')} (code: {product_code}, supplier: {product.get('supplier', 'Default')})")
            
            # Always use supplier from product (product is source of truth)
            # This ensures supplier is always populated correctly
            supplier = product.get('supplier', 'Default')
            
            try:
                order_type = item.get('order_type', 'Vial')
                qty = float(item.get('qty', 0))
                
                if qty <= 0:
                    print(f"❌ Invalid quantity for {product_code}: {qty}")
                    return jsonify({
                        'success': False,
                        'error': f'Invalid quantity for product {product_code}'
                    }), 400
                
                unit_price = product.get('kit_price') if order_type == 'Kit' else product.get('vial_price')
                if not unit_price or unit_price <= 0:
                    print(f"❌ Invalid price for {product_code}: unit_price={unit_price}, order_type={order_type}")
                    print(f"   Product data: kit_price={product.get('kit_price')}, vial_price={product.get('vial_price')}")
                    return jsonify({
                        'success': False,
                        'error': f'Invalid price for product {product_code} ({order_type})'
                    }), 400
                
                line_total_usd = unit_price * qty
                line_total_php = line_total_usd * exchange_rate
                
                items_with_prices.append({
                    'product_code': product_code,
                    'product_name': product.get('name', 'Unknown Product'),
                    'order_type': order_type,
                    'supplier': supplier,  # Always from product
                    'qty': qty,
                    'unit_price_usd': unit_price,
                    'line_total_usd': line_total_usd,
                    'line_total_php': line_total_php
                })
                total_usd += line_total_usd
                print(f"✅ Added item: {product.get('name')} ({order_type} x{qty}) = ${line_total_usd:.2f}")
            except (KeyError, TypeError, ValueError) as e:
                print(f"❌ Error calculating price for {product_code}: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({
                    'success': False,
                    'error': f'Error calculating price for product {product_code}: {str(e)}'
                }), 500
        
        total_php = total_usd * exchange_rate
        
        # Calculate tiered admin fee based on total vials
        total_vials = 0
        for item in items_with_prices:
            qty = float(item.get('qty', 0))
            order_type = item.get('order_type', 'Vial')
            product_code = str(item.get('product_code', '')).strip()
            supplier = str(item.get('supplier', 'Default')).strip()
            
            # Find product to get vials_per_kit (normalize comparison like earlier in code)
            product = None
            for p in products:
                p_code = str(p.get('code', '')).strip()
                p_supplier = str(p.get('supplier', 'Default')).strip()
                # Case-insensitive comparison for both code and supplier
                if p_code.upper() == product_code.upper() and p_supplier.upper() == supplier.upper():
                    product = p
                    break
            
            # Fallback: if not found with supplier match, try without supplier (backward compatibility)
            if not product:
                product = next((p for p in products if str(p.get('code', '')).strip().upper() == product_code.upper()), None)
            
            vials_per_kit = product.get('vials_per_kit', 10) if product else 10
            
            if order_type == 'Kit':
                total_vials += qty * vials_per_kit
            else:
                total_vials += qty
        
        # Tiered admin fee: ₱300 for every 50 vials (or part thereof)
        admin_fee_php = math.ceil(total_vials / 50) * 300 if total_vials > 0 else 0
        grand_total_php = total_php + admin_fee_php
        
        order_data = {
            'full_name': data.get('full_name', '').strip(),
            'telegram': data.get('telegram', '').strip(),
            'contact_number': data.get('contact_number', '').strip(),
            'mailing_address': data.get('mailing_address', '').strip(),
            'items': items_with_prices,
            'exchange_rate': exchange_rate,
            'grand_total_php': grand_total_php
        }
        
        # Save order to sheets
        try:
            print(f"📝 Saving order to sheets: {len(order_data['items'])} items")
            print(f"📝 Order data keys: {list(order_data.keys())}")
            print(f"📝 First item keys: {list(order_data['items'][0].keys()) if order_data['items'] else 'No items'}")
            order_id = save_order_to_sheets(order_data)
        except Exception as e:
            print(f"❌ Error saving order to sheets: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': f'Failed to save order: {str(e)}'
            }), 500
        
        if not order_id:
            return jsonify({
                'success': False,
                'error': 'Failed to save order. Please try again.'
            }), 500
        
        # Send Telegram notification (non-blocking - don't fail if this fails)
        try:
            items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']}) - ₱{item['line_total_php']:.2f}" for item in items_with_prices])
            telegram_msg = f"""🛒 <b>New Order!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order_data['full_name']}
<b>Telegram:</b> {order_data.get('telegram', 'N/A')}

<b>Items:</b>
{items_text}

<b>Subtotal (USD):</b> ${total_usd:,.2f}
<b>Subtotal (PHP):</b> ₱{total_php:,.2f}
<b>Total Vials:</b> {int(total_vials)} vials
<b>Admin Fee:</b> ₱{admin_fee_php:,.2f} (₱300 per 50 vials)
<b>Grand Total:</b> ₱{grand_total_php:,.2f}
<b>Status:</b> Pending Payment"""
            send_telegram_notification(telegram_msg)
        except Exception as e:
            print(f"⚠️ Error sending Telegram notification: {e}")
            # Don't fail the order if Telegram fails
        
        # Also notify customer if registered (non-blocking)
        try:
            notify_customer_order(order_data, order_id)
        except Exception as e:
            print(f"⚠️ Error notifying customer: {e}")
            # Don't fail the order if customer notification fails
        
        return jsonify({
            'success': True,
            'order_id': order_id,
            'order': {
                **order_data,
                'order_id': order_id,
                'admin_fee_php': ADMIN_FEE_PHP,
                'subtotal_usd': total_usd,
                'subtotal_php': total_php
            }
        })
    
    except Exception as e:
        print(f"❌ Unexpected error in api_submit_order: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred. Please try again or contact support.'
        }), 500

@app.route('/api/orders/<order_id>/add-items', methods=['POST'])
@app.route('/api/orders/add-items-by-telegram', methods=['POST'])
def api_add_items(order_id=None):
    """Add items to existing order - supports order_id or telegram username matching with comprehensive error handling"""
    try:
        # Validate request data
        if not request.json:
            return jsonify({
                'success': False,
                'error': 'Invalid request: No data provided'
            }), 400
        
        data = request.json or {}
        telegram_username = data.get('telegram_username')
        items = data.get('items', [])
        
        # Validate items
        if not items or not isinstance(items, list) or len(items) == 0:
            return jsonify({
                'success': False,
                'error': 'No items provided. Please add at least one item.'
            }), 400
        
        # Validate items structure
        for idx, item in enumerate(items):
            if not item.get('product_code'):
                return jsonify({
                    'success': False,
                    'error': f'Item {idx + 1}: Product code is required'
                }), 400
            if not isinstance(item.get('qty'), (int, float)) or item.get('qty', 0) <= 0:
                return jsonify({
                    'success': False,
                    'error': f'Item {idx + 1}: Quantity must be a positive number'
                }), 400
        
        # If order_id not in URL, try to get from request body or use telegram lookup
        if not order_id:
            order_id = data.get('order_id')
        
        # Find order by order_id or telegram_username
        order = None
        order_lookup_attempts = 0
        max_retries = 2
        
        try:
            while order_lookup_attempts < max_retries:
                order_lookup_attempts += 1
                
                if order_id:
                    order = get_order_by_id(order_id)
                    if not order and order_lookup_attempts == 1:
                        # First attempt failed - clear cache and retry
                        print(f"⚠️ Order {order_id} not found on first attempt, clearing cache and retrying...")
                        clear_cache('orders')
                        continue
                elif telegram_username:
                    if not telegram_username or not telegram_username.strip():
                        return jsonify({
                            'success': False,
                            'error': 'Telegram username is required when order_id is not provided'
                        }), 400
                    
                    # Find order by telegram username
                    try:
                        orders = get_orders_from_sheets()
                    except Exception as e:
                        print(f"❌ Error getting orders from sheets: {e}")
                        return jsonify({
                            'success': False,
                            'error': 'Failed to load orders. Please try again.'
                        }), 500
                    
                    telegram_normalized = telegram_username.lower().strip().lstrip('@')
                    found_order_id = None
                    
                    for o in orders:
                        order_telegram = str(o.get('Telegram Username', '')).lower().strip().lstrip('@')
                        if order_telegram == telegram_normalized:
                            # Get the most recent non-cancelled, non-locked order
                            order_status = o.get('Order Status', 'Pending')
                            order_locked = str(o.get('Locked', 'No')).lower() == 'yes'
                            if order_status != 'Cancelled' and not order_locked:
                                found_order_id = o.get('Order ID')
                                if found_order_id:
                                    order_id = found_order_id
                                    order = get_order_by_id(order_id)
                                    if order:
                                        break
                    
                    if not order and order_lookup_attempts == 1:
                        # First attempt failed - clear cache and retry
                        print(f"⚠️ Order for telegram {telegram_username} not found on first attempt, clearing cache and retrying...")
                        clear_cache('orders')
                        continue
                else:
                    return jsonify({
                        'success': False,
                        'error': 'Order ID or Telegram username is required'
                    }), 400
                
                # If order found or max retries reached, break
                if order or order_lookup_attempts >= max_retries:
                    break
                    
        except Exception as e:
            print(f"❌ Error finding order: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': f'Error finding order: {str(e)}. Please try again.'
            }), 500
        
        if not order:
            # Provide more detailed error message
            error_details = []
            if order_id:
                error_details.append(f"Order ID: {order_id}")
            if telegram_username:
                error_details.append(f"Telegram: {telegram_username}")
            
            error_msg = 'Order not found. '
            if order_id:
                error_msg += f'The order with ID "{order_id}" could not be found. '
            if telegram_username:
                error_msg += f'No active order found for Telegram username "{telegram_username}". '
            error_msg += 'The order may have been cancelled, locked, or does not exist. Please refresh the page and try again.'
            
            print(f"❌ Order lookup failed after {order_lookup_attempts} attempts. {', '.join(error_details)}")
            return jsonify({
                'success': False,
                'error': error_msg
            }), 404
        
        # Check if order is locked (admins can still add items to locked orders)
        is_admin = session.get('is_admin', False)
        if order.get('locked') and not is_admin:
            return jsonify({
                'success': False,
                'error': 'Order is locked and cannot be modified. Please contact admin.'
            }), 403
        
        if order.get('status') == 'Cancelled':
            return jsonify({
                'success': False,
                'error': 'Cannot add items to a cancelled order. Please create a new order.'
            }), 400
        
        # Check if order is paid - admins can add items to paid orders
        is_paid = order.get('payment_status', '').lower() == 'paid'
        if is_paid and not is_admin:
            return jsonify({
                'success': False,
                'error': 'Cannot add items to a paid order. Please contact admin.'
            }), 403
        
        # Calculate prices with error handling
        try:
            products = get_products()
        except Exception as e:
            print(f"❌ Error getting products: {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to load product information. Please try again.'
            }), 500
        
        try:
            exchange_rate = order.get('exchange_rate')
            if not exchange_rate or exchange_rate <= 0:
                exchange_rate = FALLBACK_EXCHANGE_RATE
                print(f"⚠️ Using fallback exchange rate: {exchange_rate}")
        except (KeyError, TypeError, ValueError):
            exchange_rate = FALLBACK_EXCHANGE_RATE
            print(f"⚠️ Using fallback exchange rate: {exchange_rate}")
        
        items_with_prices = []
        for idx, item in enumerate(items):
            try:
                product = next((p for p in products if p['code'] == item['product_code']), None)
                if not product:
                    return jsonify({
                        'success': False,
                        'error': f'Product {item["product_code"]} not found'
                    }), 404
                
                unit_price = product['kit_price'] if item.get('order_type') == 'Kit' else product['vial_price']
                if not unit_price or unit_price <= 0:
                    return jsonify({
                        'success': False,
                        'error': f'Invalid price for product {item["product_code"]}'
                    }), 400
                
                line_total_usd = unit_price * item['qty']
                line_total_php = line_total_usd * exchange_rate
                
                items_with_prices.append({
                    'product_code': item['product_code'],
                    'product_name': product['name'],
                    'order_type': item.get('order_type', 'Vial'),
                    'qty': item['qty'],
                    'unit_price_usd': unit_price,
                    'line_total_usd': line_total_usd,
                    'line_total_php': line_total_php
                })
            except (KeyError, TypeError, ValueError) as e:
                print(f"❌ Error processing item {idx + 1}: {e}")
                return jsonify({
                    'success': False,
                    'error': f'Error processing item {idx + 1}: {str(e)}'
                }), 500
        
        # Filter out 0 quantity items before adding
        items_with_prices = [item for item in items_with_prices if item.get('qty', 0) > 0]
        
        if not items_with_prices:
            return jsonify({
                'success': False,
                'error': 'No items with quantity > 0 to add. Please add items with quantity.'
            }), 400
        
        # Add items to order (mark as post-payment if order is paid)
        try:
            is_paid = order.get('payment_status', '').lower() == 'paid'
            success = add_items_to_order(order_id, items_with_prices, exchange_rate, 
                                        telegram_username=telegram_username, 
                                        is_post_payment=is_paid)
        except Exception as e:
            print(f"❌ Error adding items to order: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': 'Failed to add items to order. Please try again.'
            }), 500
        
        if not success:
            return jsonify({
                'success': False,
                'error': 'Failed to add items to order. Please try again.'
            }), 500
        
        # Clean up any 0-quantity rows for this order
        try:
            cleanup_zero_quantity_rows(order_id)
        except Exception as e:
            print(f"⚠️ Warning: Failed to cleanup zero-quantity rows: {e}")
            # Don't fail the request if cleanup fails
        
        # Recalculate and return updated order
        try:
            updated_order = get_order_by_id(order_id)
        except Exception as e:
            print(f"❌ Error getting updated order: {e}")
            return jsonify({
                'success': False,
                'error': 'Items added but failed to retrieve updated order. Please refresh.'
            }), 500
        
        if not updated_order:
            return jsonify({
                'success': False,
                'error': 'Items added but order not found. Please refresh.'
            }), 404
        
        # Don't send Telegram notification here - only send on finalize
        # Telegram notifications will be sent when customer clicks "Finalize Order"
        
        return jsonify({
            'success': True,
            'order_id': order_id,
            'updated_order': updated_order
        })
    
    except Exception as e:
        print(f"❌ Unexpected error in api_add_items: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred. Please try again or contact support.'
        }), 500

@app.route('/api/orders/<order_id>/update-item', methods=['POST'])
def api_update_item(order_id):
    """Update quantity of an item in an existing order"""
    order = get_order_by_id(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if order['locked']:
        return jsonify({'error': 'Order is locked'}), 403
    
    if order['status'] == 'Cancelled':
        return jsonify({'error': 'Order is cancelled'}), 403
    
    data = request.json
    product_code = data.get('product_code')
    order_type = data.get('order_type')
    new_qty = data.get('qty', 0)
    
    if not product_code or not order_type:
        return jsonify({'error': 'Missing product_code or order_type'}), 400
    
    if update_item_quantity(order_id, product_code, order_type, new_qty):
        # Don't send Telegram notification here - only send on finalize
        # Telegram notifications will be sent when customer clicks "Finalize Order"
        return jsonify({'success': True})
    
    return jsonify({'error': 'Failed to update item'}), 500

@app.route('/api/orders/<order_id>/finalize', methods=['POST'])
def api_finalize_order(order_id):
    """Finalize an order - sends Telegram notification to admin"""
    try:
        order = get_order_by_id(order_id)
        if not order:
            return jsonify({'error': 'Order not found'}), 404
        
        # Clean up 0 quantity rows before finalizing
        cleanup_zero_quantity_rows(order_id)
        
        # Recalculate totals to ensure accuracy
        recalculate_order_total(order_id)
        
        # Get fresh order data
        order = get_order_by_id(order_id)
        if not order:
            return jsonify({'error': 'Order not found after recalculation'}), 404
        
        # Send Telegram notification to PepHaul Admin
        try:
            items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']}) - ₱{item['line_total_php']:.2f}" 
                                   for item in order.get('items', []) if item.get('qty', 0) > 0])
            
            subtotal_php = sum(item.get('line_total_php', 0) for item in order.get('items', []) if item.get('qty', 0) > 0)
            grand_total_php = order.get('grand_total_php', 0)
            
            telegram_msg = f"""🛒 <b>Order Finalized!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order.get('full_name', 'N/A')}
<b>Telegram:</b> @{order.get('telegram', 'N/A').replace('@', '')}

<b>Items:</b>
{items_text}

<b>Subtotal (PHP):</b> ₱{subtotal_php:,.2f}
<b>PepHaul Admin Fee:</b> ₱{ADMIN_FEE_PHP:,.2f}
<b>Grand Total:</b> ₱{grand_total_php:,.2f}

<b>Status:</b> Finalized - Pending Payment"""
            send_telegram_notification(telegram_msg)
        except Exception as e:
            print(f"⚠️ Error sending Telegram notification: {e}")
            # Don't fail if Telegram fails
        
        # Also notify customer if registered (non-blocking)
        try:
            notify_customer_order(order, order_id)
        except Exception as e:
            print(f"⚠️ Error notifying customer: {e}")
            # Don't fail if customer notification fails
        
        return jsonify({
            'success': True,
            'order': order,
            'message': 'Order finalized successfully'
        })
    except Exception as e:
        print(f"❌ Error finalizing order: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to finalize order'}), 500

def cleanup_zero_quantity_rows(order_id=None):
    """Clean up all rows with 0 quantity from PepHaul Entry tab"""
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return None
        
        all_values = worksheet.get_all_values()
        headers = all_values[0] if all_values else []
        
        col_order_id = headers.index('Order ID') if 'Order ID' in headers else 0
        col_qty = headers.index('QTY') if 'QTY' in headers else 8
        
        # Find first row for each order (to preserve header rows)
        order_first_rows = {}
        for row_num, row in enumerate(all_values[1:], start=2):
            if len(row) > col_order_id and row[col_order_id]:
                order_id_val = row[col_order_id]
                if order_id_val not in order_first_rows:
                    order_first_rows[order_id_val] = row_num
        
        # Find all rows with 0 quantity to delete
        zero_qty_rows = []
        for row_num, row in enumerate(all_values[1:], start=2):
            if len(row) > col_qty:
                qty = int(row[col_qty] or 0) if row[col_qty] else 0
                order_id_val = row[col_order_id] if len(row) > col_order_id else ''
                
                # If order_id specified, only clean that order
                if order_id and order_id_val != order_id:
                    continue
                
                # Don't delete first row of any order (contains totals)
                if qty <= 0 and order_id_val:
                    first_row = order_first_rows.get(order_id_val)
                    if first_row and row_num != first_row:
                        zero_qty_rows.append(row_num)
                elif qty <= 0 and not order_id_val:
                    # Orphaned row with 0 qty (no order ID) - can delete
                    zero_qty_rows.append(row_num)
        
        # Delete rows in reverse order to avoid index shifting
        if zero_qty_rows:
            zero_qty_rows.sort(reverse=True)
            for row_num in zero_qty_rows:
                worksheet.delete_rows(row_num)
            print(f"🧹 Cleaned up {len(zero_qty_rows)} rows with 0 quantity" + (f" for order {order_id}" if order_id else ""))
            
            # Clear cache
            clear_cache('orders')
            clear_cache('inventory')
            clear_cache('order_stats')
        
        return True
    except Exception as e:
        print(f"❌ Error cleaning up zero quantity rows: {e}")
        import traceback
        traceback.print_exc()
        return False

def update_item_quantity(order_id, product_code, order_type, new_qty):
    """Update quantity of a specific item in an order"""
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return None
        
        # Get all data
        all_values = worksheet.get_all_values()
        headers = all_values[0] if all_values else []
        
        # Find column indices
        order_id_col = headers.index('Order ID') if 'Order ID' in headers else -1
        product_code_col = headers.index('Product Code') if 'Product Code' in headers else -1
        order_type_col = headers.index('Order Type') if 'Order Type' in headers else -1
        qty_col = headers.index('QTY') if 'QTY' in headers else -1
        unit_price_col = headers.index('Unit Price USD') if 'Unit Price USD' in headers else -1
        line_total_usd_col = headers.index('Line Total USD') if 'Line Total USD' in headers else -1
        line_total_php_col = headers.index('Line Total PHP') if 'Line Total PHP' in headers else -1
        exchange_rate_col = headers.index('Exchange Rate') if 'Exchange Rate' in headers else -1
        grand_total_col = headers.index('Grand Total PHP') if 'Grand Total PHP' in headers else -1
        
        if -1 in [order_id_col, product_code_col, order_type_col, qty_col]:
            print("Missing required columns")
            return False
        
        # Find the specific row to update
        target_row = None
        first_order_row = None
        order_rows = []
        
        for i, row in enumerate(all_values[1:], start=2):  # Start at row 2 (1-indexed, skip header)
            if len(row) > order_id_col and row[order_id_col] == order_id:
                if first_order_row is None:
                    first_order_row = i
                order_rows.append(i)
                
                if (len(row) > product_code_col and row[product_code_col] == product_code and
                    len(row) > order_type_col and row[order_type_col] == order_type):
                    target_row = i
        
        if target_row is None:
            print(f"Item not found: {product_code} / {order_type}")
            return False
        
        # Get current values
        current_row = all_values[target_row - 1]  # Convert to 0-indexed
        unit_price = float(current_row[unit_price_col]) if unit_price_col >= 0 and current_row[unit_price_col] else 0
        exchange_rate = float(current_row[exchange_rate_col]) if exchange_rate_col >= 0 and current_row[exchange_rate_col] else FALLBACK_EXCHANGE_RATE
        
        # Calculate new line totals
        new_line_total_usd = unit_price * new_qty
        new_line_total_php = new_line_total_usd * exchange_rate
        
        # If new quantity is 0 or less, delete the row (but not the first order row)
        if new_qty <= 0:
            if target_row != first_order_row:
                worksheet.delete_rows(target_row)
                # Clear cache and recalculate totals
                clear_cache('orders')
                clear_cache('inventory')
                clear_cache('order_stats')
                recalculate_order_total(order_id)
                print(f"Deleted {product_code} row (qty=0) for order {order_id}")
                return True
            else:
                # Can't delete first row, just set qty to 0
                new_qty = 0
                new_line_total_usd = 0
                new_line_total_php = 0
        
        # Update the item row
        updates = []
        updates.append({'range': f'{chr(65 + qty_col)}{target_row}', 'values': [[new_qty]]})
        
        if line_total_usd_col >= 0:
            updates.append({'range': f'{chr(65 + line_total_usd_col)}{target_row}', 'values': [[new_line_total_usd]]})
        
        if line_total_php_col >= 0:
            updates.append({'range': f'{chr(65 + line_total_php_col)}{target_row}', 'values': [[new_line_total_php]]})
        
        # Apply item updates
        for update in updates:
            worksheet.update(update['range'], update['values'])
        
        # Also check and delete any other rows with 0 quantity for this order (except first row)
        all_values_updated = worksheet.get_all_values()
        zero_qty_rows = []
        for i, row in enumerate(all_values_updated[1:], start=2):
            if len(row) > order_id_col and row[order_id_col] == order_id:
                if i != first_order_row:  # Don't delete first row
                    qty = int(row[qty_col] or 0) if len(row) > qty_col else 0
                    if qty <= 0:
                        zero_qty_rows.append(i)
        
        if zero_qty_rows:
            zero_qty_rows.sort(reverse=True)
            for row_num in zero_qty_rows:
                worksheet.delete_rows(row_num)
        
        # Recalculate grand total for the entire order
        if first_order_row and grand_total_col >= 0:
            # Get fresh data after update
            all_values = worksheet.get_all_values()
            new_subtotal_php = 0
            
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > order_id_col and row[order_id_col] == order_id:
                    if len(row) > line_total_php_col and row[line_total_php_col]:
                        try:
                            new_subtotal_php += float(row[line_total_php_col])
                        except:
                            pass
            
            new_grand_total = new_subtotal_php + ADMIN_FEE_PHP
            worksheet.update(f'{chr(65 + grand_total_col)}{first_order_row}', [[new_grand_total]])
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        print(f"Updated {product_code} qty to {new_qty} for order {order_id}")
        return True
        
    except Exception as e:
        print(f"Error updating item: {e}")
        return False

@app.route('/api/orders/<order_id>/cancel', methods=['POST'])
@app.route('/api/orders/cancel-by-telegram', methods=['POST'])
def api_cancel_order(order_id=None):
    """Cancel an order and delete all its rows from Google Sheets - supports order_id or telegram username matching"""
    data = request.json or {}
    telegram_username = data.get('telegram_username')
    
    # If order_id not in URL, try to get from request body or use telegram lookup
    if not order_id:
        order_id = data.get('order_id')
    
    # Find order by order_id or telegram_username
    order = None
    if order_id:
        order = get_order_by_id(order_id)
    elif telegram_username:
        # Find order by telegram username
        orders = get_orders_from_sheets()
        telegram_normalized = telegram_username.lower().strip().lstrip('@')
        
        # Get the most recent non-cancelled order for this telegram username
        matching_orders = []
        for o in orders:
            order_telegram = str(o.get('Telegram Username', '')).lower().strip().lstrip('@')
            if order_telegram == telegram_normalized:
                order_status = o.get('Order Status', 'Pending')
                if order_status != 'Cancelled':
                    matching_orders.append(o)
        
        if matching_orders:
            # Get the most recent order (by order date or order ID)
            matching_orders.sort(key=lambda x: x.get('Order Date', ''), reverse=True)
            order_id = matching_orders[0].get('Order ID')
            order = get_order_by_id(order_id)
    
    if not order:
        return jsonify({'error': 'Order not found. Provide order_id or telegram_username'}), 404
    
    # Verify telegram username matches if provided
    if telegram_username:
        order_telegram = str(order.get('telegram', '')).lower().strip().lstrip('@')
        provided_telegram = telegram_username.lower().strip().lstrip('@')
        if order_telegram != provided_telegram:
            return jsonify({
                'error': f'Telegram username mismatch. Order belongs to @{order.get("telegram", "unknown")}, not @{telegram_username}'
            }), 400
    
    if order['locked']:
        return jsonify({'error': 'Order is locked. Unlock it first before cancelling'}), 403
    
    # Delete all rows for this order (matching both order_id and telegram username)
    if delete_order_rows(order_id, telegram_username=order.get('telegram')):
        print(f"✅ Order {order_id} cancelled and all rows deleted (Telegram: {order.get('telegram', 'N/A')})")
        return jsonify({
            'success': True, 
            'message': f'Order {order_id} cancelled and removed from sheets',
            'order_id': order_id,
            'telegram': order.get('telegram', '')
        })
    
    return jsonify({'error': 'Failed to cancel order'}), 500

def delete_order_rows(order_id, telegram_username=None):
    """Delete all rows for a cancelled order from Google Sheets - verifies both order_id and telegram username match"""
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return None
        
        # Get all data
        all_values = worksheet.get_all_values()
        headers = all_values[0] if all_values else []
        
        # Find column indices
        col_order_id = headers.index('Order ID') if 'Order ID' in headers else 0
        col_telegram = headers.index('Telegram Username') if 'Telegram Username' in headers else 3
        
        # Normalize telegram username for comparison
        telegram_normalized = None
        if telegram_username:
            telegram_normalized = str(telegram_username).lower().strip().lstrip('@')
        
        # Find all rows belonging to this order
        order_rows = []
        for row_num, row in enumerate(all_values[1:], start=2):  # Skip header
            if len(row) > col_order_id:
                row_order_id = row[col_order_id] if len(row) > col_order_id else ''
                row_telegram = ''
                if len(row) > col_telegram:
                    row_telegram = str(row[col_telegram]).lower().strip().lstrip('@') if row[col_telegram] else ''
                
                # Check if this row belongs to the order
                if row_order_id == order_id:
                    # Verify telegram username matches if provided
                    if telegram_normalized and row_telegram:
                        if row_telegram != telegram_normalized:
                            print(f"⚠️ Telegram mismatch at row {row_num}: expected @{telegram_username}, found @{row[col_telegram] if len(row) > col_telegram else 'N/A'}")
                            continue  # Skip this row if telegram doesn't match
                    order_rows.append(row_num)
                elif order_rows and not row_order_id:
                    # Continue adding rows if they're part of the same order (empty Order ID means continuation)
                    # Check if product code exists and verify telegram if provided
                    if len(row) > 5 and row[5]:  # Product Code column
                        if telegram_normalized and row_telegram:
                            if row_telegram != telegram_normalized:
                                continue  # Skip if telegram doesn't match
                        order_rows.append(row_num)
                elif order_rows and row_order_id:
                    # New order started, stop
                    break
        
        # Also find rows by searching for order_id anywhere (for added items)
        cells = worksheet.findall(order_id)
        for cell in cells:
            if cell.row not in order_rows:
                # Verify telegram username matches if provided
                if cell.row <= len(all_values):
                    row = all_values[cell.row - 1]  # 0-indexed
                    if len(row) > col_telegram:
                        row_telegram = str(row[col_telegram]).lower().strip().lstrip('@') if row[col_telegram] else ''
                        if telegram_normalized and row_telegram:
                            if row_telegram != telegram_normalized:
                                continue  # Skip if telegram doesn't match
                    order_rows.append(cell.row)
        
        if not order_rows:
            print(f"⚠️ No rows found for order {order_id}" + (f" with telegram @{telegram_username}" if telegram_username else ""))
            return False
        
        print(f"🗑️ Deleting {len(order_rows)} rows for order {order_id}" + (f" (Telegram: @{telegram_username})" if telegram_username else "") + f": {order_rows}")
        
        # Delete rows in reverse order (from bottom to top) to avoid index shifting
        for row_num in sorted(order_rows, reverse=True):
            worksheet.delete_rows(row_num)
            print(f"  Deleted row {row_num}")
        
        print(f"✅ Successfully deleted all rows for order {order_id}" + (f" (Telegram: @{telegram_username})" if telegram_username else ""))
        
        # Clear cache since orders changed - this triggers automatic recalculation
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        # Force recalculation by getting fresh inventory stats
        # This ensures inventory is immediately updated after cancellation
        try:
            get_inventory_stats()
            print(f"✅ Inventory recalculated after cancelling order {order_id}")
        except Exception as e:
            print(f"⚠️ Warning: Could not recalculate inventory after cancellation: {e}")
        
        return True
    except Exception as e:
        print(f"❌ Error deleting order rows: {e}")
        import traceback
        traceback.print_exc()
        return False

@app.route('/api/orders/<order_id>/lock', methods=['POST'])
def api_lock_order(order_id):
    """Lock an order"""
    if update_order_status(order_id, locked=True, status='Locked'):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to lock order'}), 500

@app.route('/api/orders/<order_id>/unlock', methods=['POST'])
def api_unlock_order(order_id):
    """Unlock an order"""
    if update_order_status(order_id, locked=False, status='Pending'):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to unlock order'}), 500

@app.route('/api/orders/<order_id>/payment', methods=['POST'])
def api_upload_payment(order_id):
    """Upload payment screenshot"""
    # Pre-check: Is Drive configured?
    if not drive_service:
        print("❌ Upload attempt failed - Drive service not initialized")
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '')
        print(f"  - GOOGLE_CREDENTIALS_JSON set: {bool(creds_json)}")
        return jsonify({
            'error': 'Google Drive not configured. Please check GOOGLE_CREDENTIALS_JSON on Render.',
            'details': {'drive_configured': False}
        }), 500
    
    data = request.json
    screenshot_data = data.get('screenshot')
    
    if not screenshot_data:
        return jsonify({'error': 'No screenshot provided'}), 400
    
    print(f"📤 Attempting upload for order {order_id}")
    
    # Upload to Drive
    drive_link = upload_to_drive(screenshot_data, 'payment.jpg', order_id)
    
    if drive_link:
        # Set status to "Waiting for Confirmation" - order will be locked when admin confirms payment
        update_order_status(order_id, payment_status='Waiting for Confirmation', payment_screenshot=drive_link)
        
        # Get order details for notification
        order = get_order_by_id(order_id)
        if order:
            telegram_msg = f"""💰 <b>Payment Uploaded!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order.get('full_name', 'N/A')}
<b>Telegram:</b> {order.get('telegram', 'N/A')}
<b>Amount:</b> ₱{order.get('grand_total_php', 0):,.2f}

<b>Screenshot:</b> <a href="{drive_link}">View Payment</a>

⚠️ Please verify and confirm payment in Admin Panel."""
            send_telegram_notification(telegram_msg)
        
        print(f"✅ Upload successful: {drive_link}")
        return jsonify({'success': True, 'link': drive_link})
    
    print(f"❌ Upload failed for order {order_id}")
    return jsonify({'error': 'Upload failed - please check server logs'}), 500

@app.route('/api/orders/<order_id>/payment-link', methods=['POST'])
def api_submit_payment_link(order_id):
    """Submit payment screenshot link (Google Drive, Imgur, etc.)"""
    data = request.json
    payment_link = data.get('payment_link', '').strip()
    
    if not payment_link:
        return jsonify({'error': 'No payment link provided'}), 400
    
    # Validate URL format
    try:
        from urllib.parse import urlparse
        result = urlparse(payment_link)
        if not all([result.scheme, result.netloc]):
            raise ValueError("Invalid URL")
    except:
        return jsonify({'error': 'Invalid URL format'}), 400
    
    print(f"🔗 Payment link submitted for order {order_id}: {payment_link}")
    
    # Update order with payment link - set to "Waiting for Confirmation" until admin confirms
    if update_order_status(order_id, payment_status='Waiting for Confirmation', payment_screenshot=payment_link):
        # Get order details for notification
        order = get_order_by_id(order_id)
        if order:
            telegram_msg = f"""💰 <b>Payment Link Submitted!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order.get('full_name', 'N/A')}
<b>Telegram:</b> {order.get('telegram', 'N/A')}
<b>Amount:</b> ₱{order.get('grand_total_php', 0):,.2f}

<b>Payment Link:</b> <a href="{payment_link}">View Payment</a>

⚠️ Please verify and confirm payment in Admin Panel."""
            send_telegram_notification(telegram_msg)
        
        print(f"✅ Payment link saved successfully")
        return jsonify({'success': True, 'link': payment_link})
    
    print(f"❌ Failed to save payment link for order {order_id}")
    return jsonify({'error': 'Failed to save payment link'}), 500

@app.route('/api/mark-payment-sent/<order_id>', methods=['POST'])
def api_mark_payment_sent(order_id):
    """Mark payment as sent to PepHaul Admin - updates status to Waiting for Confirmation"""
    print(f"📤 Marking payment as sent for order: {order_id}")
    
    # Update order status to Waiting for Confirmation
    if update_order_status(order_id, payment_status='Waiting for Confirmation'):
        # Get order details for notification
        order = get_order_by_id(order_id)
        if order:
            telegram_msg = f"""💸 <b>Payment Sent Notification!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order.get('full_name', 'N/A')}
<b>Telegram:</b> @{order.get('telegram', 'N/A').replace('@', '')}
<b>Amount:</b> ₱{order.get('grand_total_php', 0):,.2f}

Customer has marked payment as sent to PepHaul Admin.
⏳ Status: <b>Waiting for Confirmation</b>

Please check GCash and confirm payment in Admin Panel."""
            send_telegram_notification(telegram_msg)
        
        # Also notify customer if registered (non-blocking)
        try:
            notify_customer_payment_sent(order, order_id)
        except Exception as e:
            print(f"⚠️ Error notifying customer: {e}")
            # Don't fail if customer notification fails
        
        print(f"✅ Payment marked as sent - status updated to Waiting for Confirmation")
        return jsonify({'success': True, 'message': 'Payment marked as sent! PepHaul Admin will be notified.'})
    
    print(f"❌ Failed to mark payment as sent for order {order_id}")
    return jsonify({'error': 'Failed to update payment status'}), 500

@app.route('/api/upload-payment', methods=['POST'])
def api_upload_payment_generic():
    """Upload payment screenshot (generic endpoint)"""
    # Pre-check: Is Drive configured?
    if not drive_service:
        print("❌ Upload attempt failed - Drive service not initialized")
        print(f"  - sheets_client: {sheets_client is not None}")
        print(f"  - drive_service: {drive_service is not None}")
        creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON', '')
        print(f"  - GOOGLE_CREDENTIALS_JSON set: {bool(creds_json)}")
        print(f"  - GOOGLE_CREDENTIALS_JSON length: {len(creds_json) if creds_json else 0}")
        return jsonify({
            'error': 'Google Drive not configured. Please check GOOGLE_CREDENTIALS_JSON on Render.',
            'details': {
                'drive_configured': False,
                'sheets_configured': sheets_client is not None,
                'creds_set': bool(creds_json)
            }
        }), 500
    
    data = request.json
    order_id = data.get('order_id')
    file_data = data.get('file_data')
    file_name = data.get('file_name', 'payment.jpg')
    
    if not order_id:
        return jsonify({'error': 'No order ID provided'}), 400
    
    if not file_data:
        return jsonify({'error': 'No file data provided'}), 400
    
    print(f"📤 Attempting upload for order {order_id}")
    
    # Upload to Drive
    drive_link = upload_to_drive(file_data, file_name, order_id)
    
    if drive_link:
        # Set status to "Waiting for Confirmation" - order will be locked when admin confirms payment
        update_order_status(order_id, payment_status='Waiting for Confirmation', payment_screenshot=drive_link)
        
        # Get order details for notification
        order = get_order_by_id(order_id)
        if order:
            telegram_msg = f"""💰 <b>Payment Uploaded!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order.get('full_name', 'N/A')}
<b>Telegram:</b> {order.get('telegram', 'N/A')}
<b>Amount:</b> ₱{order.get('grand_total_php', 0):,.2f}

<b>Screenshot:</b> <a href="{drive_link}">View Payment</a>

⚠️ Please verify and confirm payment in Admin Panel."""
            send_telegram_notification(telegram_msg)
        
        print(f"✅ Upload successful: {drive_link}")
        return jsonify({'success': True, 'link': drive_link})
    
    print(f"❌ Upload failed for order {order_id}")
    return jsonify({'error': 'Upload failed - please check server logs'}), 500

@app.route('/api/orders/<order_id>/mailing-address', methods=['POST'])
def api_save_mailing_address(order_id):
    """Save mailing address for an order (only for paid orders)"""
    data = request.json
    mailing_name = data.get('mailing_name', '')
    mailing_phone = data.get('mailing_phone', '')
    mailing_address = data.get('mailing_address', '')
    
    if not mailing_name or not mailing_phone or not mailing_address:
        return jsonify({'error': 'All fields are required'}), 400
    
    if not sheets_client:
        return jsonify({'error': 'Sheets not configured'}), 500
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return None
        
        # Find the order's first row
        cell = worksheet.find(order_id)
        if not cell:
            return jsonify({'error': 'Order not found'}), 404
        
        # Ensure headers exist in columns U, V, W (21, 22, 23)
        headers = worksheet.row_values(1)
        if len(headers) < 21:
            # Extend headers if needed
            while len(headers) < 23:
                headers.append('')
            worksheet.update('A1:W1', [headers])
        
        # Set headers for columns U, V, W if not already set
        if len(headers) < 21 or headers[20] != 'Full Name':
            worksheet.update_cell(1, 21, 'Full Name')
        if len(headers) < 22 or headers[21] != 'Contact Number':
            worksheet.update_cell(1, 22, 'Contact Number')
        if len(headers) < 23 or headers[22] != 'Mailing Address':
            worksheet.update_cell(1, 23, 'Mailing Address')
        
        # Update the order row with mailing info in columns U (21), V (22), W (23)
        worksheet.update_cell(cell.row, 21, mailing_name)  # Column U
        worksheet.update_cell(cell.row, 22, mailing_phone)  # Column V
        worksheet.update_cell(cell.row, 23, mailing_address)  # Column W
        
        # Lock the order (Column P = 16) when shipping details are added
        # Ensure header exists
        if len(headers) < 16 or headers[15] != 'Locked':
            worksheet.update_cell(1, 16, 'Locked')
        # Set order to locked
        worksheet.update_cell(cell.row, 16, 'Yes')
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        # Send notification to admin (non-blocking - don't fail if this fails)
        try:
            order = get_order_by_id(order_id)
            if order:
                telegram_msg = f"""📬 <b>Mailing Address Added!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order.get('full_name', 'N/A')}
<b>Telegram:</b> {order.get('telegram', 'N/A')}

<b>Shipping To:</b>
{mailing_name}
{mailing_phone}
{mailing_address}

✅ Ready for fulfillment!"""
                send_telegram_notification(telegram_msg)
                
                # Also notify customer if registered (non-blocking)
                try:
                    notify_customer_shipping_details(order, order_id, mailing_name, mailing_phone, mailing_address)
                except Exception as customer_notify_error:
                    print(f"⚠️ Error notifying customer: {customer_notify_error}")
                    # Don't fail if customer notification fails
        except Exception as notify_error:
            print(f"⚠️ Error sending notification (address saved successfully): {notify_error}")
            # Don't fail the save if notification fails
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error saving mailing address: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/orders/<order_id>/tracking-number', methods=['POST'])
def api_save_tracking_number(order_id):
    """Admin: Save tracking number for an order (only for paid orders with shipping details)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    tracking_number = data.get('tracking_number', '').strip()
    
    if not tracking_number:
        return jsonify({'error': 'Tracking number is required'}), 400
    
    if not sheets_client:
        return jsonify({'error': 'Sheets not configured'}), 500
    
    try:
        # Verify order exists and is paid with shipping details
        order = get_order_by_id(order_id)
        if not order:
            return jsonify({'error': 'Order not found'}), 404
        
        payment_status = order.get('payment_status', '').lower()
        if payment_status != 'paid':
            return jsonify({'error': 'Tracking number can only be added for paid orders'}), 400
        
        mailing_address = order.get('mailing_address', '')
        if not mailing_address or not mailing_address.strip():
            return jsonify({'error': 'Shipping details must be added before tracking number'}), 400
        
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return jsonify({'error': 'Worksheet not found'}), 404
        
        # Find the order's first row
        cell = worksheet.find(order_id)
        if not cell:
            return jsonify({'error': 'Order not found in sheets'}), 404
        
        # Ensure headers exist - column X (24) for Tracking Number
        headers = worksheet.row_values(1)
        if len(headers) < 24:
            # Extend headers if needed
            while len(headers) < 24:
                headers.append('')
            worksheet.update('A1:X1', [headers])
        
        # Set header for column X if not already set
        if len(headers) < 24 or headers[23] != 'Tracking Number':
            worksheet.update_cell(1, 24, 'Tracking Number')
        
        # Update the order row with tracking number in column X (24)
        worksheet.update_cell(cell.row, 24, tracking_number)
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        # Send notification to admin (non-blocking)
        try:
            telegram_msg = f"""📦 <b>Tracking Number Added!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order.get('full_name', 'N/A')}
<b>Telegram:</b> {order.get('telegram', 'N/A')}
<b>Tracking Number:</b> {tracking_number}

✅ Order is ready for shipment!"""
            send_telegram_notification(telegram_msg)
        except Exception as notify_error:
            print(f"⚠️ Error sending notification (tracking number saved successfully): {notify_error}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error saving tracking number: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# Telegram customer notifications storage (in-memory, consider using database for production)
telegram_customers = {}  # {telegram_username: chat_id}

def send_customer_telegram(chat_id, message, parse_mode='HTML'):
    """Send notification to a specific customer via Telegram"""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': parse_mode
        }
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending customer Telegram: {e}")
        return False

@app.route('/api/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """Handle incoming Telegram messages (for customer registration)"""
    try:
        data = request.json
        message = data.get('message', {})
        chat_id = message.get('chat', {}).get('id')
        text = message.get('text', '')
        username = message.get('from', {}).get('username', '')
        first_name = message.get('from', {}).get('first_name', '')
        
        # Check if this is the admin (@dee_jay)
        is_admin = username.lower() == 'dee_jay'
        
        if text.startswith('/start'):
            # Register customer for notifications
            if username:
                telegram_customers[username.lower()] = chat_id
                telegram_customers[f"@{username.lower()}"] = chat_id
                print(f"Registered Telegram customer: @{username} -> {chat_id}")
                
                # If admin, also set as admin chat ID
                if is_admin:
                    # Store admin chat ID in environment (for current session)
                    global TELEGRAM_ADMIN_CHAT_ID
                    TELEGRAM_ADMIN_CHAT_ID = str(chat_id)
                    print(f"✅ PepHaul Admin registered: @{username} (chat_id: {chat_id})")
            
            # Send welcome message
            if is_admin:
                welcome_msg = f"""🎉 <b>Welcome PepHaul Admin, {first_name}!</b> 👑

You're now registered as the <b>PepHaul Admin</b>.

You'll receive notifications for:
• 📦 New orders
• 💸 Payment status updates
• ⏳ Orders waiting for confirmation

<i>Your Telegram: @{username}</i>

Admin panel: https://pephaul-order-form.onrender.com/admin

Ready to manage orders! 💜✨"""
            else:
                welcome_msg = f"""🎉 <b>Welcome to PepHaul Bot, {first_name}!</b>

You're now registered to receive order notifications!

When you place an order on our website with your Telegram username, you'll receive:
• ✅ Order confirmation
• 📦 Order updates
• 💳 Payment reminders

<i>Your Telegram: @{username}</i>

Thank you for joining PepHaul! 💜✨"""
            
            send_customer_telegram(chat_id, welcome_msg)
        
        return jsonify({'ok': True})
    except Exception as e:
        print(f"Telegram webhook error: {e}")
        return jsonify({'ok': False}), 500

@app.route('/api/telegram/set-webhook', methods=['POST'])
def set_telegram_webhook():
    """Set up Telegram webhook (admin only)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({'error': 'Telegram bot token not configured'}), 400
    
    try:
        # Get the webhook URL from request or construct from host
        webhook_url = request.json.get('webhook_url')
        if not webhook_url:
            webhook_url = f"{request.host_url}api/telegram/webhook"
        
        # Set webhook
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        response = requests.post(url, json={'url': webhook_url}, timeout=10)
        result = response.json()
        
        if result.get('ok'):
            return jsonify({'success': True, 'message': f'Webhook set to: {webhook_url}'})
        else:
            return jsonify({'success': False, 'error': result.get('description', 'Unknown error')})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def notify_customer_order(order_data, order_id):
    """Send order confirmation to customer via Telegram - auto-resolves username to chat ID"""
    telegram_handle = order_data.get('telegram', '').strip().lower()
    if not telegram_handle:
        return False
    
    # Clean up the handle
    if telegram_handle.startswith('@'):
        telegram_handle = telegram_handle[1:]
    
    # Try to resolve username to chat ID (using the same helper function)
    chat_id = resolve_telegram_recipient(telegram_handle)
    
    if not chat_id:
        print(f"⚠️ Customer @{telegram_handle} not found - they need to message @{TELEGRAM_BOT_USERNAME} first")
        print(f"   Once they message the bot, they'll automatically receive notifications for future orders")
        return False
    
    items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']})" for item in order_data.get('items', [])])
    
    message = f"""✨ <b>Order Confirmed!</b> ✨

<b>Order ID:</b> {order_id}
<b>Name:</b> {order_data.get('full_name', '')}

<b>Your Items:</b>
{items_text}

<b>Grand Total:</b> ₱{order_data.get('grand_total_php', 0):,.2f}

📱 Please complete your payment and upload the screenshot on the order form.

Thank you for your order! 💜"""
    
    return send_customer_telegram(chat_id, message)

def notify_customer_payment_sent(order_data, order_id):
    """Send payment sent confirmation to customer via Telegram - auto-resolves username to chat ID"""
    telegram_handle = order_data.get('telegram', '').strip().lower()
    if not telegram_handle:
        return False
    
    # Clean up the handle
    if telegram_handle.startswith('@'):
        telegram_handle = telegram_handle[1:]
    
    # Try to resolve username to chat ID
    chat_id = resolve_telegram_recipient(telegram_handle)
    
    if not chat_id:
        print(f"⚠️ Customer @{telegram_handle} not found - they need to message @{TELEGRAM_BOT_USERNAME} first")
        return False
    
    message = f"""💸 <b>Payment Sent Confirmation</b>

<b>Order ID:</b> {order_id}
<b>Amount:</b> ₱{order_data.get('grand_total_php', 0):,.2f}

✅ Your payment has been marked as sent to PepHaul Admin.

⏳ Status: <b>Waiting for Confirmation</b>

The admin will verify your payment and update your order status. You'll be notified once confirmed!

Thank you! 💜"""
    
    return send_customer_telegram(chat_id, message)

def notify_customer_shipping_details(order_data, order_id, mailing_name, mailing_phone, mailing_address):
    """Send shipping details confirmation to customer via Telegram - auto-resolves username to chat ID"""
    telegram_handle = order_data.get('telegram', '').strip().lower()
    if not telegram_handle:
        return False
    
    # Clean up the handle
    if telegram_handle.startswith('@'):
        telegram_handle = telegram_handle[1:]
    
    # Try to resolve username to chat ID
    chat_id = resolve_telegram_recipient(telegram_handle)
    
    if not chat_id:
        print(f"⚠️ Customer @{telegram_handle} not found - they need to message @{TELEGRAM_BOT_USERNAME} first")
        return False
    
    message = f"""📬 <b>Shipping Details Confirmed!</b>

<b>Order ID:</b> {order_id}

<b>Shipping Address:</b>
{mailing_name}
{mailing_phone}
{mailing_address}

✅ Your shipping details have been saved successfully!

Your order is ready for fulfillment. If you need to update your shipping address, please contact PepHaul admin.

Thank you! 💜"""
    
    return send_customer_telegram(chat_id, message)

@app.route('/api/admin/orders')
def api_admin_orders():
    """Get all orders for admin panel"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Clear cache to ensure fresh data (admin needs latest)
    clear_cache('orders')
    orders = get_orders_from_sheets()
    
    print(f"📊 Admin panel: Loaded {len(orders)} raw order records from sheets")
    
    # Debug: Show first few records to understand structure
    if orders and len(orders) > 0:
        print(f"📋 First record keys: {list(orders[0].keys())[:15]}")
        first_order_id = orders[0].get('Order ID', None)
        print(f"📋 First record Order ID: {repr(first_order_id)}")
        first_product_code = orders[0].get('Product Code', None)
        print(f"📋 First record Product Code: {repr(first_product_code)}")
    
    # Group by Order ID with full details
    grouped = {}
    orders_without_id = 0
    orders_processed = 0
    
    for order in orders:
        # Find Order ID column dynamically (handle variations)
        order_id = None
        order_id_key_found = None
        for key in order.keys():
            if 'order' in key.lower() and 'id' in key.lower():
                value = order.get(key, None)
                if value is not None:
                    value_str = str(value).strip()
                    if value_str:  # Only use if non-empty
                        order_id = value_str
                        order_id_key_found = key
                        break
        
        # Fallback to common variations
        if not order_id:
            for fallback_key in ['Order ID', 'order id', 'OrderID', 'Order Id']:
                value = order.get(fallback_key, None)
                if value is not None:
                    value_str = str(value).strip()
                    if value_str:
                        order_id = value_str
                        order_id_key_found = fallback_key
                        break
        
        if not order_id or not str(order_id).strip():
            orders_without_id += 1
            if orders_without_id <= 3:
                print(f"⚠️ Skipping record without Order ID: keys={list(order.keys())[:5]}")
            continue
        
        orders_processed += 1
        
        # Find telegram column dynamically (handle variations)
        telegram_value = None
        telegram_key_found = None
        for key in order.keys():
            if 'telegram' in key.lower():
                value = order.get(key, None)
                if value is not None:
                    value_str = str(value).strip()
                    if value_str:  # Only use if non-empty
                        telegram_value = value
                        telegram_key_found = key
                        break
        
        # Fallback to common variations if not found
        if telegram_value is None:
            for fallback_key in ['Telegram Username', 'telegram username', 'Telegram Username ', 'TelegramUsername']:
                value = order.get(fallback_key, None)
                if value is not None:
                    value_str = str(value).strip()
                    if value_str:
                        telegram_value = value
                        telegram_key_found = fallback_key
                        break
        
        # Default to empty string if still not found
        if telegram_value is None:
            telegram_value = ''
        
        # Debug: Log first few orders being processed
        if orders_processed <= 5:
            print(f"  [{orders_processed}] Processing Order {order_id}: telegram_key='{telegram_key_found}', telegram='{telegram_value}'")
        
        if order_id not in grouped:
            grouped[order_id] = {
                'order_id': order_id,
                'order_date': order.get('Order Date', ''),
                'full_name': order.get('Name', order.get('Full Name', '')),
                'telegram': telegram_value,
                'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                'status': order.get('Order Status', 'Pending'),
                'locked': str(order.get('Locked', 'No')).lower() == 'yes',
                'payment_status': order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid')),
                'payment_screenshot': order.get('Link to Payment', order.get('Payment Screenshot Link', order.get('Payment Screenshot', ''))),
                'contact_number': order.get('Contact Number', ''),
                'mailing_address': order.get('Mailing Address', ''),
                'items': []
            }
        
        # Add items (only if Product Code exists)
        product_code = order.get('Product Code', '')
        product_code_raw = str(product_code) if product_code is not None else 'None'
        
        if product_code and str(product_code).strip():
            qty = int(order.get('QTY', 0) or 0)
            # Include all items, even with qty 0 (admin should see everything)
            grouped[order_id]['items'].append({
                'product_code': product_code,
                'product_name': order.get('Product Name', ''),
                'order_type': order.get('Order Type', ''),
                'qty': qty,
                'unit_price_usd': float(order.get('Unit Price USD', 0) or 0),
                'line_total_php': float(order.get('Line Total PHP', 0) or 0)
            })
        elif orders_processed <= 10:  # Debug: Log why items aren't being added
            print(f"    ⚠️ Order {order_id} row skipped (no Product Code): product_code={repr(product_code_raw)}")
    
    print(f"📊 Admin panel: Processed {orders_processed} records with Order IDs, {orders_without_id} without Order IDs")
    print(f"📊 Admin panel: Grouped into {len(grouped)} unique orders")
    
    # Debug: Log ALL orders (not just samples) to see what's being returned
    if grouped:
        print(f"📋 All grouped orders:")
        for oid, order_data in grouped.items():
            print(f"  Order {oid}: name='{order_data['full_name']}', telegram='{order_data['telegram']}', items={len(order_data['items'])}, status='{order_data['status']}'")
    else:
        print(f"⚠️ WARNING: No orders grouped! This means no orders have Order IDs or all were filtered out.")
        # Debug: Show what we have
        if orders:
            print(f"📋 Sample raw records (first 10):")
            for i, order in enumerate(orders[:10]):
                print(f"  Record {i+1}: {dict(list(order.items())[:10])}")
        else:
            print(f"⚠️ CRITICAL: No orders returned from get_orders_from_sheets() at all!")
    
    # Filter out orders with no items (these are likely header rows or empty rows)
    # But keep orders even if they have 0 quantity items (admin should see everything)
    orders_with_items = {oid: order_data for oid, order_data in grouped.items() if len(order_data['items']) > 0}
    orders_without_items = len(grouped) - len(orders_with_items)
    
    if orders_without_items > 0:
        print(f"⚠️ Filtered out {orders_without_items} orders with no items (likely empty/header rows)")
    
    # Sort by date (newest first)
    sorted_orders = sorted(orders_with_items.values(), key=lambda x: x.get('order_date', '') or '', reverse=True)
    print(f"📊 Admin panel: Returning {len(sorted_orders)} orders to frontend (after filtering empty orders)")
    return jsonify(sorted_orders)

@app.route('/api/admin/orders/<order_id>/confirm-payment', methods=['POST'])
def api_admin_confirm_payment(order_id):
    """Admin: Confirm payment for an order"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Lock the order when payment is confirmed (paid orders cannot be modified)
    if update_order_status(order_id, payment_status='Paid', locked=True):
        # Get order details for notifications
        order = get_order_by_id(order_id)
        if order:
            items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']})" for item in order.get('items', [])])
            
            # Notify PepHaul Admin via Telegram
            admin_msg = f"""✅ <b>Payment Confirmed!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order.get('full_name', '')}
<b>Telegram:</b> @{order.get('telegram', 'N/A').replace('@', '')}

<b>Items:</b>
{items_text}

<b>Grand Total:</b> ₱{order.get('grand_total_php', 0):,.2f}

Payment has been confirmed and order is ready for fulfillment."""
            send_telegram_notification(admin_msg)
            
            # Try to notify customer via Telegram
            telegram_handle = order.get('telegram', '').strip().lower()
            if telegram_handle:
                if telegram_handle.startswith('@'):
                    telegram_handle = telegram_handle[1:]
                
                chat_id = telegram_customers.get(telegram_handle) or telegram_customers.get(f"@{telegram_handle}")
                
                if chat_id:
                    customer_msg = f"""✅ <b>Payment Confirmed!</b> ✅

<b>Order ID:</b> {order_id}
<b>Name:</b> {order.get('full_name', '')}

<b>Your Items:</b>
{items_text}

<b>Grand Total:</b> ₱{order.get('grand_total_php', 0):,.2f}

🎉 Your payment has been confirmed! Your order is now being processed.

Thank you for your order! 💜"""
                    
                    send_customer_telegram(chat_id, customer_msg)
                    print(f"✅ Payment confirmation sent to customer @{telegram_handle}")
                else:
                    print(f"⚠️ Customer @{telegram_handle} hasn't messaged @{TELEGRAM_BOT_USERNAME} yet")
        
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to confirm payment'}), 500

@app.route('/api/admin/orders/<order_id>/notify-customer', methods=['POST'])
def api_admin_notify_customer(order_id):
    """Admin: Send payment confirmation notification to customer via Telegram"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Get order details
    order = get_order_by_id(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    # Check if payment is confirmed
    if order.get('payment_status') != 'Paid':
        return jsonify({'error': 'Order payment not confirmed yet'}), 400
    
    telegram_handle = order.get('telegram', '').strip().lower()
    if not telegram_handle:
        return jsonify({'error': 'No Telegram username found for this order'}), 400
    
    # Remove @ if present
    if telegram_handle.startswith('@'):
        telegram_handle = telegram_handle[1:]
    
    # Check if customer has messaged the bot
    chat_id = telegram_customers.get(telegram_handle) or telegram_customers.get(f"@{telegram_handle}")
    
    if not chat_id:
        return jsonify({
            'error': f'Customer @{telegram_handle} hasn\'t messaged @{TELEGRAM_BOT_USERNAME} yet',
            'telegram_handle': telegram_handle,
            'bot_username': TELEGRAM_BOT_USERNAME
        }), 404
    
    # Send notification
    items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']})" for item in order.get('items', [])])
    
    customer_msg = f"""✅ <b>Payment Confirmed!</b> ✅

<b>Order ID:</b> {order_id}
<b>Name:</b> {order.get('full_name', '')}

<b>Your Items:</b>
{items_text}

<b>Grand Total:</b> ₱{order.get('grand_total_php', 0):,.2f}

🎉 Your payment has been confirmed! Your order is now being processed.

Thank you for your order! 💜"""
    
    if send_customer_telegram(chat_id, customer_msg):
        print(f"✅ Manual payment confirmation sent to customer @{telegram_handle}")
        return jsonify({
            'success': True,
            'message': f'Payment confirmation sent to @{telegram_handle} via Telegram'
        })
    else:
        return jsonify({'error': 'Failed to send Telegram notification'}), 500

@app.route('/api/admin/orders/<order_id>/lock', methods=['POST'])
def api_admin_lock_order(order_id):
    """Admin: Lock/unlock a specific order"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    is_locked = data.get('locked', True)
    
    # If unlocking, check if order has payment status that makes it non-editable
    # If so, reset payment status to 'Unpaid' to make it editable again
    payment_status_to_reset = None
    if not is_locked:
        order = get_order_by_id(order_id)
        if order:
            current_payment_status = order.get('payment_status', '').lower()
            if current_payment_status in ['paid', 'waiting for confirmation']:
                payment_status_to_reset = 'Unpaid'
    
    if update_order_status(order_id, locked=is_locked, payment_status=payment_status_to_reset):
        action = 'locked' if is_locked else 'unlocked'
        if payment_status_to_reset:
            print(f"✅ Order {order_id} {action} and payment status reset to Unpaid")
        else:
            print(f"✅ Order {order_id} {action}")
        return jsonify({'success': True, 'message': f'Order {action} successfully'})
    
    return jsonify({'error': 'Failed to update order lock status'}), 500

@app.route('/api/admin/orders/bulk-lock', methods=['POST'])
def api_admin_bulk_lock_orders():
    """Admin: Lock/unlock multiple orders at once"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    order_ids = data.get('order_ids', [])
    is_locked = data.get('locked', True)
    
    if not order_ids:
        return jsonify({'error': 'No order IDs provided'}), 400
    
    success_count = 0
    failed_count = 0
    
    for order_id in order_ids:
        if update_order_status(order_id, locked=is_locked):
            success_count += 1
        else:
            failed_count += 1
    
    action = 'locked' if is_locked else 'unlocked'
    print(f"✅ Bulk {action}: {success_count} succeeded, {failed_count} failed")
    
    return jsonify({
        'success': True,
        'message': f'{success_count} orders {action} successfully',
        'success_count': success_count,
        'failed_count': failed_count
    })

@app.route('/api/admin/confirm-payment', methods=['POST'])
def api_admin_confirm_payment_post():
    """Admin: Confirm payment for an order (POST with body)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    order_id = data.get('order_id')
    
    if not order_id:
        return jsonify({'error': 'Order ID required'}), 400
    
    # Lock the order when payment is confirmed (paid orders cannot be modified)
    if update_order_status(order_id, payment_status='Paid', locked=True):
        # Get order details for customer notification
        order = get_order_by_id(order_id)
        if order:
            # Send notification to customer via Telegram
            telegram_handle = order.get('telegram', '').strip().lower()
            if telegram_handle:
                if telegram_handle.startswith('@'):
                    telegram_handle = telegram_handle[1:]
                
                chat_id = telegram_customers.get(telegram_handle) or telegram_customers.get(f"@{telegram_handle}")
                
                if chat_id:
                    items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']})" for item in order.get('items', [])])
                    
                    customer_msg = f"""✅ <b>Payment Confirmed!</b> ✅

<b>Order ID:</b> {order_id}
<b>Name:</b> {order.get('full_name', '')}

<b>Your Items:</b>
{items_text}

<b>Grand Total:</b> ₱{order.get('grand_total_php', 0):,.2f}

🎉 Your payment has been confirmed by admin! Your order is now being processed.

Thank you for your order! 💜"""
                    
                    send_customer_telegram(chat_id, customer_msg)
                    print(f"✅ Payment confirmation sent to customer @{telegram_handle}")
                else:
                    print(f"⚠️ Customer @{telegram_handle} not registered for Telegram notifications")
        
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to confirm payment'}), 500

@app.route('/api/admin/orders/<order_id>/mark-unpaid', methods=['POST'])
def api_admin_mark_unpaid(order_id):
    """Admin: Mark order as unpaid"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if update_order_status(order_id, payment_status='Unpaid'):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to update payment status'}), 500

@app.route('/api/admin/customer-summary')
def api_admin_customer_summary():
    """Get customer summary - unique customers with order counts, total vials, and grand totals"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    orders = get_orders_from_sheets()
    products = get_products()
    
    # Build product lookup for vials_per_kit
    product_vials_map = {p['code']: p.get('vials_per_kit', VIALS_PER_KIT) for p in products}
    
    # Group orders by customer name
    customer_summary = {}
    order_grand_totals = {}  # Track grand totals per order_id to avoid double counting
    order_payment_status = {}  # Track payment status per order_id
    
    for order in orders:
        order_id = order.get('Order ID', '')
        if not order_id:
            continue
        
        # Get customer name
        customer_name = order.get('Name', order.get('Full Name', ''))
        if not customer_name:
            continue
        
        # Initialize customer if not exists
        if customer_name not in customer_summary:
            customer_summary[customer_name] = {
                'customer_name': customer_name,
                'order_count': 0,
                'order_ids': set(),
                'total_vials': 0,
                'total_grand_total_php': 0
            }
        
        # Track grand total for this order (store once per order_id)
        grand_total = float(order.get('Grand Total PHP', 0) or 0)
        if order_id not in order_grand_totals and grand_total > 0:
            order_grand_totals[order_id] = grand_total
        
        # Track payment status for this order (store once per order_id)
        payment_status = order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid'))
        if order_id not in order_payment_status:
            order_payment_status[order_id] = payment_status
        
        # Track unique orders (only count once per order_id)
        if order_id not in customer_summary[customer_name]['order_ids']:
            customer_summary[customer_name]['order_ids'].add(order_id)
            customer_summary[customer_name]['order_count'] += 1
            # Add grand total (only once per order)
            if order_id in order_grand_totals:
                customer_summary[customer_name]['total_grand_total_php'] += order_grand_totals[order_id]
        
        # Calculate vials for this item
        product_code = order.get('Product Code', '')
        order_type = order.get('Order Type', 'Vial')
        qty = int(order.get('QTY', 0) or 0)
        
        if product_code and qty > 0:
            if order_type == 'Kit':
                # Kit = 10 vials (or product's vials_per_kit)
                vials_per_kit = product_vials_map.get(product_code, VIALS_PER_KIT)
                vials = qty * vials_per_kit
            else:
                # Vial = 1 vial
                vials = qty
            
            customer_summary[customer_name]['total_vials'] += vials
    
    # Convert to list and sort by total grand total (descending)
    result = []
    for name, data in customer_summary.items():
        # Get order IDs as sorted list for display
        order_ids_list = sorted(list(data['order_ids']))
        order_numbers = ', '.join(order_ids_list)
        
        # Determine payment status: if all orders are paid, show "Paid", otherwise show "Unpaid" or mixed status
        payment_statuses = [order_payment_status.get(order_id, 'Unpaid') for order_id in order_ids_list]
        if all(status == 'Paid' for status in payment_statuses):
            payment_status = 'Paid'
        elif any(status == 'Paid' for status in payment_statuses):
            payment_status = 'Partially Paid'
        elif any(status == 'Waiting for Confirmation' for status in payment_statuses):
            payment_status = 'Waiting for Confirmation'
        else:
            payment_status = 'Unpaid'
        
        result.append({
            'customer_name': name,
            'order_count': data['order_count'],
            'order_numbers': order_numbers,
            'total_vials': data['total_vials'],
            'payment_status': payment_status,
            'total_grand_total_php': round(data['total_grand_total_php'], 2)
        })
    
    result.sort(key=lambda x: x['total_grand_total_php'], reverse=True)
    
    return jsonify(result)

@app.route('/api/admin/orders/<order_id>/update-item', methods=['POST'])
def api_admin_update_item(order_id):
    """Admin: Update quantity of an item in an existing order"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    order = get_order_by_id(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    data = request.json
    product_code = data.get('product_code')
    order_type = data.get('order_type')
    new_qty = data.get('qty', 0)
    
    if not product_code or not order_type:
        return jsonify({'error': 'Missing product_code or order_type'}), 400
    
    if update_item_quantity(order_id, product_code, order_type, new_qty):
        # Clear cache and reload to ensure inventory is recalculated
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        # Recalculate order total
        recalculate_order_total(order_id)
        return jsonify({'success': True, 'message': 'Item updated successfully'})
    
    return jsonify({'error': 'Failed to update item'}), 500

@app.route('/api/admin/orders/<order_id>/send-reminder', methods=['POST'])
def api_admin_send_reminder(order_id):
    """Admin: Send payment reminder via Telegram"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({'error': 'Telegram bot not configured'}), 500
    
    # Get order details
    order = get_order_by_id(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    telegram_handle = order.get('telegram', '').strip().lower()
    if not telegram_handle:
        return jsonify({'error': 'No Telegram username found for this order'}), 400
    
    # Remove @ if present
    if telegram_handle.startswith('@'):
        telegram_handle = telegram_handle[1:]
    
    # Check if we have their chat_id
    chat_id = telegram_customers.get(telegram_handle) or telegram_customers.get(f"@{telegram_handle}")
    
    if not chat_id:
        return jsonify({
            'error': f'Cannot send reminder to @{telegram_handle}',
            'message': f'Customer needs to message @{TELEGRAM_BOT_USERNAME} on Telegram first.\n\nOnce they send any message to the bot, you can send reminders.'
        }), 400
    
    # Create reminder message
    grand_total = order.get('grand_total_php', 0)
    items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']})" for item in order.get('items', [])])
    
    message = f"""🔔 <b>Payment Reminder - PepHaul Order</b>

<b>Order ID:</b> {order_id}
<b>Name:</b> {order.get('full_name', '')}

<b>Your Items:</b>
{items_text}

<b>Total Amount:</b> ₱{grand_total:,.2f}

Dear customer, this is a friendly reminder that we haven't received your payment yet.

Please send your payment and upload the screenshot through the order form:
https://pephaul-order-form.onrender.com

If you've already paid, please upload your payment screenshot so we can confirm your order.

Thank you! 💜"""
    
    # Send reminder
    if send_customer_telegram(chat_id, message):
        return jsonify({'success': True, 'message': f'Reminder sent to @{telegram_handle}'})
    else:
        return jsonify({'error': 'Failed to send Telegram message'}), 500


# PepHaul Entry Tab Management
CURRENT_PEPHAUL_TAB = 'PepHaul Entry-01'  # Default tab name

def get_current_pephaul_tab():
    """Get the current active PepHaul Entry tab name"""
    # Try to get from session, fallback to default
    try:
        return session.get('current_pephaul_tab', CURRENT_PEPHAUL_TAB)
    except:
        # If session not available (e.g., in background tasks), use default
        return CURRENT_PEPHAUL_TAB

def set_current_pephaul_tab(tab_name):
    """Set the current active PepHaul Entry tab name"""
    try:
        session['current_pephaul_tab'] = tab_name
    except:
        pass  # Session not available in some contexts

def get_pephaul_worksheet(spreadsheet=None):
    """Get the current PepHaul Entry worksheet"""
    if not spreadsheet:
        if not sheets_client:
            return None
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
    
    tab_name = get_current_pephaul_tab()
    try:
        return spreadsheet.worksheet(tab_name)
    except:
        # Fallback to default if tab doesn't exist
        try:
            return spreadsheet.worksheet('PepHaul Entry-01')
        except:
            # Last resort: try old name
            try:
                return spreadsheet.worksheet('PepHaul Entry')
            except:
                return None

@app.route('/api/admin/pephaul-tabs', methods=['GET'])
def api_admin_list_pephaul_tabs():
    """Get list of available PepHaul Entry tabs"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Try to initialize Google services if not already initialized
        global sheets_client
        if not sheets_client:
            print("⚠️ Sheets client not initialized, attempting to initialize...")
            init_google_services()
        
        if not sheets_client:
            error_msg = (
                'Google Sheets client not configured. '
                'Please set GOOGLE_CREDENTIALS_JSON environment variable or place credentials.json file in project root.'
            )
            print(f"❌ {error_msg}")
            return jsonify({
                'error': error_msg,
                'details': 'Google Sheets integration requires credentials. Check server logs for initialization errors.'
            }), 500
        
        print(f"📋 Fetching PepHaul Entry tabs from Google Sheets...")
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        all_sheets = spreadsheet.worksheets()
        
        # Filter tabs that start with "PepHaul Entry"
        pephaul_tabs = [ws.title for ws in all_sheets if ws.title.startswith('PepHaul Entry')]
        print(f"📋 Found {len(pephaul_tabs)} PepHaul Entry tabs: {pephaul_tabs}")
        
        # Sort tabs: "PepHaul Entry-01" first, then other numbered ones, then old "PepHaul Entry"
        def sort_key(name):
            if name == 'PepHaul Entry-01':
                return (0, 1)  # Highest priority
            if name == 'PepHaul Entry':
                return (1, 0)  # Second priority (old name)
            # Extract number from "PepHaul Entry-02", "PepHaul Entry-03", etc.
            if '-' in name:
                try:
                    num = int(name.split('-')[-1])
                    return (1, num)  # After -01, sorted by number
                except:
                    return (2, name)
            return (2, name)
        
        pephaul_tabs.sort(key=sort_key)
        
        current_tab = get_current_pephaul_tab()
        print(f"📋 Current tab: {current_tab}")
        
        return jsonify({
            'success': True,
            'tabs': pephaul_tabs,
            'current_tab': current_tab
        })
    except Exception as e:
        print(f"❌ Error listing tabs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'details': 'Check server logs for more information',
            'type': type(e).__name__
        }), 500

@app.route('/api/admin/pephaul-tabs/create', methods=['POST'])
def api_admin_create_pephaul_tab():
    """Create a new PepHaul Entry tab"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if not sheets_client:
        return jsonify({'error': 'Sheets not configured'}), 500
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        all_sheets = spreadsheet.worksheets()
        
        # Find existing PepHaul Entry tabs
        existing_tabs = [ws.title for ws in all_sheets if ws.title.startswith('PepHaul Entry')]
        
        # Determine next tab number
        next_num = 1
        for tab_name in existing_tabs:
            if '-' in tab_name:
                try:
                    num = int(tab_name.split('-')[-1])
                    if num >= next_num:
                        next_num = num + 1
                except:
                    pass
        
        # Create new tab name (e.g., "PepHaul Entry-01")
        new_tab_name = f"PepHaul Entry-{next_num:02d}"
        
        # Create new worksheet with headers (Supplier in column E)
        worksheet = spreadsheet.add_worksheet(title=new_tab_name, rows=1000, cols=25)
        headers = [
            'Order ID', 'Order Date', 'Name', 'Telegram Username', 'Supplier',
            'Product Code', 'Product Name', 'Order Type', 'QTY', 'Unit Price USD',
            'Line Total USD', 'Exchange Rate', 'Line Total PHP', 'Admin Fee PHP',
            'Grand Total PHP', 'Order Status', 'Locked', 'Payment Status', 
            'Remarks', 'Link to Payment', 'Payment Date', 'Full Name', 'Contact Number', 'Mailing Address', 'Tracking Number'
        ]
        worksheet.update('A1:Y1', [headers])
        
        print(f"✅ Created new PepHaul Entry tab: {new_tab_name}")
        
        return jsonify({
            'success': True,
            'tab_name': new_tab_name,
            'message': f'Created new tab: {new_tab_name}'
        })
    except Exception as e:
        print(f"Error creating tab: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/pephaul-tabs/switch', methods=['POST'])
def api_admin_switch_pephaul_tab():
    """Switch to a different PepHaul Entry tab"""
    try:
        if not session.get('is_admin'):
            return jsonify({'error': 'Unauthorized'}), 401
        
        if not sheets_client:
            print("❌ Sheets client not configured")
            return jsonify({'error': 'Sheets not configured'}), 500
        
        data = request.json or {}
        tab_name = data.get('tab_name', '').strip()
        
        if not tab_name:
            return jsonify({'error': 'Tab name is required'}), 400
        
        print(f"🔄 Switching to PepHaul Entry tab: {tab_name}")
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Verify tab exists
        try:
            worksheet = spreadsheet.worksheet(tab_name)
            print(f"✅ Tab '{tab_name}' found")
        except Exception as e:
            print(f"❌ Tab '{tab_name}' not found: {e}")
            return jsonify({'error': f'Tab "{tab_name}" not found'}), 404
        
        # Set as current tab
        set_current_pephaul_tab(tab_name)
        print(f"✅ Set current tab to: {tab_name}")
        
        # Clear cache to force reload from new tab
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        # Clear timeline cache for all tabs (will reload for new tab)
        for key in list(_cache.keys()):
            if key.startswith('timeline_entries_'):
                clear_cache(key)
        
        print(f"✅ Switched to PepHaul Entry tab: {tab_name}")
        
        return jsonify({
            'success': True,
            'tab_name': tab_name,
            'message': f'Switched to tab: {tab_name}'
        })
    except Exception as e:
        print(f"❌ Error switching tab: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'details': 'Check server logs for more information'}), 500

@app.route('/api/admin/orders/backfill-suppliers', methods=['POST'])
def api_admin_backfill_suppliers():
    """Admin: Backfill missing supplier information in existing orders based on product codes"""
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    if not sheets_client:
        return jsonify({'success': False, 'error': 'Google Sheets not configured'}), 500
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = get_pephaul_worksheet(spreadsheet)
        if not worksheet:
            return jsonify({'success': False, 'error': 'PepHaul Entry worksheet not found'}), 404
        
        # Get all values
        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) <= 1:
            return jsonify({'success': True, 'updated': 0, 'message': 'No orders found'})
        
        # Get headers
        headers = _normalize_order_sheet_headers(all_values[0])
        supplier_col_idx = headers.index('Supplier') if 'Supplier' in headers else None
        product_code_col_idx = headers.index('Product Code') if 'Product Code' in headers else None
        
        if supplier_col_idx is None or product_code_col_idx is None:
            return jsonify({'success': False, 'error': 'Required columns not found'}), 400
        
        # Get products to build product_code -> supplier map
        products = get_products()
        code_to_supplier_map = {}
        code_to_suppliers_map = defaultdict(set)
        for p in products:
            code = p['code']
            supplier = p.get('supplier', 'Default')
            code_to_suppliers_map[code].add(supplier)
            if code not in code_to_supplier_map:
                code_to_supplier_map[code] = supplier
        
        # Find rows that need supplier backfill
        updates = []
        updated_count = 0
        
        for row_idx, row in enumerate(all_values[1:], start=2):  # Start from row 2 (skip header)
            # Pad row if needed
            while len(row) <= max(supplier_col_idx, product_code_col_idx):
                row.append('')
            
            supplier_value = row[supplier_col_idx].strip() if len(row) > supplier_col_idx else ''
            product_code = row[product_code_col_idx].strip() if len(row) > product_code_col_idx else ''
            
            # If supplier is missing but product code exists, infer supplier
            if not supplier_value and product_code:
                if product_code in code_to_supplier_map:
                    # Unique code - use mapped supplier
                    inferred_supplier = code_to_supplier_map[product_code]
                elif product_code in code_to_suppliers_map:
                    # Multiple suppliers - default to first one (usually WWB)
                    inferred_supplier = sorted(code_to_suppliers_map[product_code])[0]
                else:
                    # Product code not found - skip
                    continue
                
                # Add to updates
                updates.append({
                    'range': f'E{row_idx}',  # Column E is Supplier
                    'values': [[inferred_supplier]]
                })
                updated_count += 1
        
        # Batch update if there are updates
        if updates:
            # Google Sheets API allows up to 100 updates per batch
            batch_size = 100
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                worksheet.batch_update(batch)
            
            # Clear cache to refresh data
            clear_cache('orders')
            clear_cache('inventory_stats')
            clear_cache('consolidated_order_stats')
        
        return jsonify({
            'success': True,
            'updated': updated_count,
            'message': f'Successfully backfilled suppliers for {updated_count} order rows'
        })
    
    except Exception as e:
        print(f"❌ Error backfilling suppliers: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/admin/pephaul-tabs/rename', methods=['POST'])
def api_admin_rename_pephaul_tab():
    """Rename a PepHaul Entry tab (e.g., rename 'PepHaul Entry' to 'PepHaul Entry-01')"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if not sheets_client:
        return jsonify({'error': 'Sheets not configured'}), 500
    
    data = request.json or {}
    old_name = data.get('old_name', '').strip()
    new_name = data.get('new_name', '').strip()
    
    if not old_name or not new_name:
        return jsonify({'error': 'Both old_name and new_name are required'}), 400
    
    if old_name == new_name:
        return jsonify({'error': 'Old and new names are the same'}), 400
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Verify old tab exists
        try:
            worksheet = spreadsheet.worksheet(old_name)
        except:
            return jsonify({'error': f'Tab "{old_name}" not found'}), 404
        
        # Check if new name already exists
        all_sheets = [ws.title for ws in spreadsheet.worksheets()]
        if new_name in all_sheets:
            return jsonify({'error': f'Tab "{new_name}" already exists'}), 400
        
        # Rename the tab
        worksheet.update_title(new_name)
        
        # If this was the current tab, update session
        current_tab = get_current_pephaul_tab()
        if current_tab == old_name:
            set_current_pephaul_tab(new_name)
        
        # Clear cache
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        print(f"✅ Renamed tab from '{old_name}' to '{new_name}'")
        
        return jsonify({
            'success': True,
            'old_name': old_name,
            'new_name': new_name,
            'message': f'Renamed tab from "{old_name}" to "{new_name}"'
        })
    except Exception as e:
        print(f"Error renaming tab: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# Initialize on startup
init_google_services()
ensure_worksheets_exist()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=os.getenv('FLASK_DEBUG', 'true').lower() == 'true', host='0.0.0.0', port=port)
