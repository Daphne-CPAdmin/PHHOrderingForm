"""
PepHaul Order Form - Web Application
Full order management with payment tracking and admin controls
"""

from flask import Flask, render_template, request, jsonify, session
import requests
import json
import os
import base64
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import defaultdict
from functools import wraps
import secrets
import time

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
TELEGRAM_ADMIN_CHAT_ID = os.getenv('TELEGRAM_ADMIN_CHAT_ID', '')  # Admin's Telegram chat ID
TELEGRAM_BOT_USERNAME = os.getenv('TELEGRAM_BOT_USERNAME', 'pephaul_bot')  # Bot username (without @)

# Simple cache to reduce Google Sheets API calls
_cache = {}
_cache_timestamps = {}
CACHE_DURATION = 30  # seconds

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

def send_telegram_notification(message, parse_mode='HTML'):
    """Send notification to admin via Telegram bot"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        print("Telegram not configured - skipping notification")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': TELEGRAM_ADMIN_CHAT_ID,
            'text': message,
            'parse_mode': parse_mode
        }
        response = requests.post(url, data=data, timeout=10)
        if response.status_code == 200:
            print(f"Telegram notification sent successfully")
            return True
        else:
            print(f"Telegram notification failed: {response.text}")
            return False
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")
        return False
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
        
        # PepHaul Entry tab
        if 'PepHaul Entry' not in existing_sheets:
            worksheet = spreadsheet.add_worksheet(title='PepHaul Entry', rows=1000, cols=25)
            headers = [
                'Order ID', 'Order Date', 'Name', 'Telegram Username',
                'Product Code', 'Product Name', 'Order Type', 'QTY', 'Unit Price USD',
                'Line Total USD', 'Exchange Rate', 'Line Total PHP', 'Admin Fee PHP',
                'Grand Total PHP', 'Order Status', 'Locked', 'Payment Status', 
                'Remarks', 'Link to Payment', 'Payment Date', 'Full Name', 'Contact Number', 'Mailing Address'
            ]
            worksheet.update('A1:W1', [headers])
        
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
        
        # PepHauler Orders tab (consolidated orders view) - create if doesn't exist
        if 'PepHauler Orders' not in existing_sheets:
            worksheet = spreadsheet.add_worksheet(title='PepHauler Orders', rows=1000, cols=15)
            headers = [
                'Order ID', 'Order Date', 'Customer Name', 'Email', 'Telegram Username',
                'Items Summary', 'Total Items', 'Grand Total PHP', 'Exchange Rate',
                'Order Status', 'Locked', 'Payment Status', 'Link to Payment',
                'Mailing Address', 'Remarks'
            ]
            worksheet.update('A1:O1', [headers])
            
    except Exception as e:
        print(f"Error ensuring worksheets: {e}")

def populate_pephauler_orders_tab():
    """Populate or update the PepHauler Orders tab with consolidated order data"""
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Check if tab exists, create if not
        try:
            worksheet = spreadsheet.worksheet('PepHauler Orders')
        except:
            worksheet = spreadsheet.add_worksheet(title='PepHauler Orders', rows=1000, cols=15)
            headers = [
                'Order ID', 'Order Date', 'Customer Name', 'Email', 'Telegram Username',
                'Items Summary', 'Total Items', 'Grand Total PHP', 'Exchange Rate',
                'Order Status', 'Locked', 'Payment Status', 'Link to Payment',
                'Mailing Address', 'Remarks'
            ]
            worksheet.update('A1:O1', [headers])
        
        # Get all orders from PepHaul Entry
        orders = get_orders_from_sheets()
        
        if not orders:
            print("No orders found to populate PepHauler Orders tab")
            return True
        
        # Group orders by Order ID
        grouped_orders = {}
        for order in orders:
            order_id = order.get('Order ID', '')
            if not order_id:
                continue
            
            if order_id not in grouped_orders:
                grouped_orders[order_id] = {
                    'order_id': order_id,
                    'order_date': order.get('Order Date', ''),
                    'customer_name': order.get('Name', order.get('Full Name', '')),
                    'email': order.get('Email', ''),
                    'telegram': order.get('Telegram Username', ''),
                    'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                    'exchange_rate': float(order.get('Exchange Rate', FALLBACK_EXCHANGE_RATE) or FALLBACK_EXCHANGE_RATE),
                    'order_status': order.get('Order Status', 'Pending'),
                    'locked': order.get('Locked', 'No'),
                    'payment_status': order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid')),
                    'payment_screenshot': order.get('Link to Payment', order.get('Payment Screenshot Link', order.get('Payment Screenshot', ''))),
                    'full_name': order.get('Full Name', order.get('Name', '')),
                    'contact_number': order.get('Contact Number', ''),
                    'mailing_address': order.get('Mailing Address', ''),
                    'remarks': order.get('Remarks', ''),
                    'items': []
                }
            
            # Add item to order
            if order.get('Product Code'):
                product_code = order.get('Product Code', '')
                product_name = order.get('Product Name', '')
                order_type = order.get('Order Type', 'Vial')
                qty = int(order.get('QTY', 0) or 0)
                
                if qty > 0:
                    grouped_orders[order_id]['items'].append({
                        'product_code': product_code,
                        'product_name': product_name,
                        'order_type': order_type,
                        'qty': qty
                    })
        
        # Prepare rows for the consolidated view
        rows = []
        for order_id, order_data in sorted(grouped_orders.items(), key=lambda x: x[1]['order_date'], reverse=True):
            # Create items summary
            items_summary_parts = []
            total_items = 0
            for item in order_data['items']:
                items_summary_parts.append(f"{item['product_code']} ({item['order_type']} x{item['qty']})")
                total_items += item['qty']
            items_summary = ', '.join(items_summary_parts) if items_summary_parts else 'No items'
            
            row = [
                order_data['order_id'],
                order_data['order_date'],
                order_data['customer_name'],
                order_data['email'],
                order_data['telegram'],
                items_summary,
                total_items,
                order_data['grand_total_php'],
                order_data['exchange_rate'],
                order_data['order_status'],
                order_data['locked'],
                order_data['payment_status'],
                order_data['payment_screenshot'],
                order_data['mailing_address'],
                order_data['remarks']
            ]
            rows.append(row)
        
        # Clear existing data (keep headers)
        if len(rows) > 0:
            # Clear all rows except header
            worksheet.clear()
            # Add headers back
            headers = [
                'Order ID', 'Order Date', 'Customer Name', 'Email', 'Telegram Username',
                'Items Summary', 'Total Items', 'Grand Total PHP', 'Exchange Rate',
                'Order Status', 'Locked', 'Payment Status', 'Link to Payment',
                'Mailing Address', 'Remarks'
            ]
            worksheet.update('A1:O1', [headers])
            # Add order data
            if rows:
                range_start = f'A2'
                range_end = f'O{len(rows) + 1}'
                worksheet.update(f'{range_start}:{range_end}', rows)
                print(f"✅ Populated PepHauler Orders tab with {len(rows)} orders")
        
        return True
        
    except Exception as e:
        print(f"Error populating PepHauler Orders tab: {e}")
        import traceback
        traceback.print_exc()
        return False

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
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = spreadsheet.worksheet('Product Locks')
        
        # Find existing row or add new
        try:
            cell = worksheet.find(product_code)
            row = cell.row
        except:
            # Add new row
            all_values = worksheet.get_all_values()
            row = len(all_values) + 1
            worksheet.update_cell(row, 1, product_code)
        
        # Update values
        if max_kits is not None:
            worksheet.update_cell(row, 2, max_kits)
        worksheet.update_cell(row, 3, 'Yes' if is_locked else 'No')
        worksheet.update_cell(row, 4, datetime.now().strftime('%Y-%m-%d %H:%M:%S') if is_locked else '')
        worksheet.update_cell(row, 5, admin_name if is_locked else '')
        
        return True
    except Exception as e:
        print(f"Error setting product lock: {e}")
        return False

# In-memory order form lock (persists while server runs, or use Google Sheets for persistence)
_order_form_locked = False
_order_form_lock_message = ""

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
                    _order_form_lock_message = record.get('Value', '')
                    
        except Exception as e:
            print(f"Error getting order form lock: {e}")
    
    return {'is_locked': _order_form_locked, 'message': _order_form_lock_message}

def get_order_form_lock():
    """Get order form lock status (cached)"""
    return get_cached('settings_lock', _fetch_order_form_lock, cache_duration=300)  # 5 minutes

def set_order_form_lock(is_locked, message=''):
    """Set order form lock status"""
    global _order_form_locked, _order_form_lock_message
    _order_form_locked = is_locked
    _order_form_lock_message = message
    
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
            worksheet.update_cell(message_row, 2, message)
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

def get_order_goal():
    """Get order goal from Settings sheet (cached)"""
    return get_cached('settings_goal', _fetch_order_goal, cache_duration=300)  # 5 minutes

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
        worksheet = spreadsheet.worksheet('PepHaul Entry')
        
        # Check if worksheet has data before trying to get records
        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) <= 1:
            # Empty worksheet or only headers, return empty list
            return []
        
        records = worksheet.get_all_records()
        # Ensure we return a list
        if not isinstance(records, list):
            return []
        
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

def get_orders_from_sheets():
    """Read existing orders from PepHaul Entry tab (cached)"""
    return get_cached('orders', _fetch_orders_from_sheets, cache_duration=120)  # 2 minutes

def get_order_by_id(order_id):
    """Get a specific order by ID"""
    orders = get_orders_from_sheets()
    order_items = [o for o in orders if o.get('Order ID') == order_id]
    
    if not order_items:
        return None
    
    # Reconstruct order
    first_item = order_items[0]
    order = {
        'order_id': order_id,
        'order_date': first_item.get('Order Date', ''),
        'full_name': first_item.get('Name', first_item.get('Full Name', '')),
        'telegram': first_item.get('Telegram Username', ''),
        'exchange_rate': float(first_item.get('Exchange Rate', FALLBACK_EXCHANGE_RATE) or FALLBACK_EXCHANGE_RATE),
        'admin_fee_php': float(first_item.get('Admin Fee PHP', ADMIN_FEE_PHP) or 0),
        'grand_total_php': float(first_item.get('Grand Total PHP', 0) or 0),
        'status': first_item.get('Order Status', 'Pending'),
        'locked': str(first_item.get('Locked', 'No')).lower() == 'yes',
        'payment_status': first_item.get('Payment Status', first_item.get('Confirmed Paid?', 'Unpaid')),
        'payment_screenshot': first_item.get('Link to Payment', first_item.get('Payment Screenshot Link', first_item.get('Payment Screenshot', ''))),
        'full_name': first_item.get('Full Name', first_item.get('Name', '')),
        'contact_number': first_item.get('Contact Number', ''),
        'mailing_address': first_item.get('Mailing Address', ''),
        'items': []
    }
    
    for item in order_items:
        if item.get('Product Code'):
            order['items'].append({
                'product_code': item.get('Product Code', ''),
                'product_name': item.get('Product Name', ''),
                'order_type': item.get('Order Type', 'Vial'),
                'qty': int(item.get('QTY', 0) or 0),
                'unit_price_usd': float(item.get('Unit Price USD', 0) or 0),
                'line_total_usd': float(item.get('Line Total USD', 0) or 0),
                'line_total_php': float(item.get('Line Total PHP', 0) or 0)
            })
    
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
        worksheet = spreadsheet.worksheet('PepHaul Entry')
        
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
                order_id,                           # All rows have Order ID
                order_date,                         # All rows have Order Date
                order_data['full_name'],            # All rows have Name
                order_data['telegram'],             # All rows have Telegram
                item['product_code'],
                item.get('product_name', ''),
                item['order_type'],
                item['qty'],
                item.get('unit_price_usd', 0),
                item.get('line_total_usd', 0),
                order_data.get('exchange_rate', FALLBACK_EXCHANGE_RATE),
                item.get('line_total_php', 0),
                ADMIN_FEE_PHP if i == 0 else '',             # Only first row
                order_data.get('grand_total_php', 0) if i == 0 else '',  # Only first row
                'Pending' if i == 0 else '',                 # Only first row
                'No' if i == 0 else '',                      # Only first row (Locked)
                'Unpaid' if i == 0 else '',                  # Only first row (Payment Status)
                '',                                          # Remarks - only first row
                '',                                          # Link to Payment - only first row
                '',                                          # Payment Date - only first row
                order_data.get('full_name', ''),            # Full Name - only first row
                order_data.get('contact_number', ''),       # Contact Number - only first row
                order_data.get('mailing_address', '')       # Mailing Address - only first row
            ]
            rows_to_add.append(row)
        
        if rows_to_add:
            end_row = next_row + len(rows_to_add) - 1
            worksheet.update(f'A{next_row}:W{end_row}', rows_to_add)
        
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
        worksheet = spreadsheet.worksheet('PepHaul Entry')
        
        # Find all rows with this order ID
        cells = worksheet.findall(order_id)
        
        for cell in cells:
            row = cell.row
            if status:
                worksheet.update_cell(row, 16, status)  # Order Status
            if locked is not None:
                worksheet.update_cell(row, 17, 'Yes' if locked else 'No')
            if payment_status:
                worksheet.update_cell(row, 18, payment_status)  # Payment Status (column S)
            if payment_screenshot:
                worksheet.update_cell(row, 19, payment_screenshot)  # Link to Payment (column T)
                worksheet.update_cell(row, 20, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))  # Payment Date (column U)
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        return True
    except Exception as e:
        print(f"Error updating order: {e}")
        return False

def add_items_to_order(order_id, new_items, exchange_rate):
    """Add items to an existing order - consolidates duplicate product codes"""
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = spreadsheet.worksheet('PepHaul Entry')
        
        # Get all existing data
        all_values = worksheet.get_all_values()
        headers = all_values[0] if all_values else []
        
        # Find column indices
        col_indices = {
            'order_id': headers.index('Order ID') if 'Order ID' in headers else 0,
            'product_code': headers.index('Product Code') if 'Product Code' in headers else 5,
            'order_type': headers.index('Order Type') if 'Order Type' in headers else 7,
            'qty': headers.index('QTY') if 'QTY' in headers else 8,
            'unit_price': headers.index('Unit Price USD') if 'Unit Price USD' in headers else 9,
            'line_total_usd': headers.index('Line Total USD') if 'Line Total USD' in headers else 10,
            'line_total_php': headers.index('Line Total PHP') if 'Line Total PHP' in headers else 12,
        }
        
        # Find existing items for this order
        existing_items = {}  # key: (product_code, order_type) -> row_number
        for row_num, row in enumerate(all_values[1:], start=2):  # Skip header, 1-indexed for sheets
            if len(row) > col_indices['order_id'] and row[col_indices['order_id']] == order_id:
                product_code = row[col_indices['product_code']] if len(row) > col_indices['product_code'] else ''
                order_type = row[col_indices['order_type']] if len(row) > col_indices['order_type'] else ''
                if product_code:
                    existing_items[(product_code, order_type)] = row_num
        
        items_to_add = []
        
        for item in new_items:
            key = (item['product_code'], item['order_type'])
            
            if key in existing_items:
                # Consolidate: Update existing row by adding quantity
                row_num = existing_items[key]
                current_row = all_values[row_num - 1]  # 0-indexed for array
                current_qty = int(current_row[col_indices['qty']] or 0)
                new_qty = current_qty + item['qty']
                unit_price = float(item.get('unit_price_usd', 0))
                new_line_total_usd = unit_price * new_qty
                new_line_total_php = new_line_total_usd * exchange_rate
                
                # Update qty and totals
                worksheet.update_cell(row_num, col_indices['qty'] + 1, new_qty)
                worksheet.update_cell(row_num, col_indices['line_total_usd'] + 1, new_line_total_usd)
                worksheet.update_cell(row_num, col_indices['line_total_php'] + 1, new_line_total_php)
            else:
                # New item - add to list
                items_to_add.append(item)
        
        # Add any truly new items (with full customer info for easy lookup)
        if items_to_add:
            next_row = len(all_values) + 1
            
            # Get customer info from the first row of this order
            order_info = {'full_name': '', 'telegram': '', 'order_date': ''}
            col_full_name = headers.index('Name') if 'Name' in headers else (headers.index('Full Name') if 'Full Name' in headers else 2)
            col_telegram = headers.index('Telegram Username') if 'Telegram Username' in headers else 3
            col_order_date = headers.index('Order Date') if 'Order Date' in headers else 1
            
            for row in all_values[1:]:
                if len(row) > col_indices['order_id'] and row[col_indices['order_id']] == order_id:
                    order_info['full_name'] = row[col_full_name] if len(row) > col_full_name else ''
                    order_info['telegram'] = row[col_telegram] if len(row) > col_telegram else ''
                    order_info['order_date'] = row[col_order_date] if len(row) > col_order_date else ''
                    break
            
            rows_to_add = []
            for item in items_to_add:
                row = [
                    order_id,                           # All rows have Order ID
                    order_info['order_date'],           # All rows have Order Date
                    order_info['full_name'],            # All rows have Name
                    order_info['telegram'],             # All rows have Telegram
                    item['product_code'],
                    item.get('product_name', ''),
                    item['order_type'],
                    item['qty'],
                    item.get('unit_price_usd', 0),
                    item.get('line_total_usd', 0),
                    exchange_rate,
                    item.get('line_total_php', 0),
                    '',                                 # Admin Fee - only on first row
                    '',                                 # Grand Total - only on first row
                    '',                                 # Order Status - only on first row
                    '',                                 # Locked - only on first row
                    '',                                 # Payment Status - only on first row
                    f'Added to {order_id}',            # Remarks
                    '',                                 # Link to Payment
                    '',                                 # Payment Date
                    '',                                 # Full Name
                    '',                                 # Contact Number
                    ''                                  # Mailing Address
                ]
                rows_to_add.append(row)
            
            end_row = next_row + len(rows_to_add) - 1
            worksheet.update(f'A{next_row}:W{end_row}', rows_to_add)
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        # Recalculate totals
        recalculate_order_total(order_id)
        
        return True
    except Exception as e:
        print(f"Error adding items: {e}")
        return False

def recalculate_order_total(order_id):
    """Recalculate order total after adding items"""
    order = get_order_by_id(order_id)
    if not order:
        return
    
    total_usd = sum(item['line_total_usd'] for item in order['items'])
    total_php = total_usd * order['exchange_rate']
    grand_total = total_php + ADMIN_FEE_PHP
    
    # Update first row with new total
    if sheets_client:
        try:
            spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
            worksheet = spreadsheet.worksheet('PepHaul Entry')
            cell = worksheet.find(order_id)
            if cell:
                worksheet.update_cell(cell.row, 15, grand_total)
        except:
            pass

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
    """Internal function to fetch and calculate inventory statistics"""
    try:
        orders = get_orders_from_sheets()
        if not orders:
            orders = []
        
        product_stats = defaultdict(lambda: {'total_vials': 0, 'kit_orders': 0, 'vial_orders': 0})
        
        # Build product lookup for vials_per_kit
        products = get_products()
        product_vials_map = {p['code']: p.get('vials_per_kit', VIALS_PER_KIT) for p in products}
        
        for order in orders:
            if order.get('Order Status') == 'Cancelled':
                continue
                
            product_code = order.get('Product Code', '')
            if not product_code:
                continue
                
            order_type = order.get('Order Type', 'Vial')
            qty = int(order.get('QTY', 0) or 0)
            vials_per_kit = product_vials_map.get(product_code, VIALS_PER_KIT)
            
            if order_type == 'Kit':
                product_stats[product_code]['total_vials'] += qty * vials_per_kit
                product_stats[product_code]['kit_orders'] += qty
            else:
                product_stats[product_code]['total_vials'] += qty
                product_stats[product_code]['vial_orders'] += qty
        
        # Get product locks
        locks = get_product_locks()
        
        inventory = {}
        for product_code, stats in product_stats.items():
            vials_per_kit = product_vials_map.get(product_code, VIALS_PER_KIT)
            total_vials = stats['total_vials']
            kits_generated = total_vials // vials_per_kit
            remaining_vials = total_vials % vials_per_kit
            slots_to_next_kit = vials_per_kit - remaining_vials if remaining_vials > 0 else 0
            
            lock_info = locks.get(product_code, {})
            max_kits = lock_info.get('max_kits', MAX_KITS_DEFAULT)
            is_locked = lock_info.get('is_locked', False) or kits_generated >= max_kits
            
            inventory[product_code] = {
                'total_vials': total_vials,
                'kits_generated': kits_generated,
                'remaining_vials': remaining_vials,
                'slots_to_next_kit': slots_to_next_kit,
                'vials_per_kit': vials_per_kit,
                'max_kits': max_kits,
                'is_locked': is_locked
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
    return get_cached('inventory', _fetch_inventory_stats, cache_duration=120)  # 2 minutes

def _fetch_products_from_sheets():
    """Internal function to fetch products from Price List tab"""
    if not sheets_client:
        return None
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        
        # Try to find Price List worksheet
        try:
            worksheet = spreadsheet.worksheet('Price List')
        except:
            # Try alternative names
            try:
                worksheet = spreadsheet.worksheet('Pricelist')
            except:
                worksheet = spreadsheet.worksheet('Products')
        
        # Get all records
        records = worksheet.get_all_records()
        
        products = []
        for record in records:
            # Handle different column name variations
            code = record.get('Product Code') or record.get('Code') or record.get('code', '').strip()
            name = record.get('Product Name') or record.get('Product') or record.get('Name') or record.get('name', '').strip()
            kit_price_str = str(record.get('USD Kit Price') or record.get('Kit Price') or record.get('kit_price') or record.get('Kit', '0')).strip()
            vial_price_str = str(record.get('USD Price/Vial') or record.get('Vial Price') or record.get('vial_price') or record.get('Vial', '0')).strip()
            vials_per_kit_str = str(record.get('Vials/Kit') or record.get('Vials Per Kit') or record.get('vials_per_kit') or '10').strip()
            
            # Skip empty rows
            if not code or not name:
                continue
            
            # Parse prices (remove $ and commas)
            try:
                kit_price = float(kit_price_str.replace('$', '').replace(',', '').strip() or 0)
                vial_price = float(vial_price_str.replace('$', '').replace(',', '').strip() or 0)
                vials_per_kit = int(float(vials_per_kit_str.strip() or 10))
            except (ValueError, AttributeError):
                continue
            
            # Skip if prices are 0
            if kit_price == 0 and vial_price == 0:
                continue
            
            products.append({
                'code': code,
                'name': name,
                'kit_price': kit_price,
                'vial_price': vial_price,
                'vials_per_kit': vials_per_kit
            })
        
        return products if products else None
        
    except Exception as e:
        print(f"Error reading products from sheet: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_products():
    """Get products from Google Sheet Price List tab, fallback to hardcoded list"""
    # Try to get from sheet first (with caching)
    try:
        cached_products = get_cached('products_sheet', _fetch_products_from_sheets, cache_duration=300)  # 5 minutes
        if cached_products and len(cached_products) > 0:
            print(f"Loaded {len(cached_products)} products from Google Sheet")
            return cached_products
    except Exception as e:
        print(f"Error loading products from sheet, using fallback: {e}")
    
    # Fallback to hardcoded list
    print("Using hardcoded product list (fallback)")
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
    """Internal function to calculate consolidated order stats"""
    try:
        orders = get_orders_from_sheets()
        if not orders:
            orders = []
        
        products = get_products()
        product_prices = {p['code']: {'kit_price': p['kit_price'], 'vial_price': p['vial_price']} for p in products}
        
        total_kits_usd = 0.0
        total_vials_usd = 0.0
        total_kits_count = 0
        total_vials_count = 0
        
        for order in orders:
            if order.get('Order Status') == 'Cancelled':
                continue
            
            product_code = order.get('Product Code', '')
            order_type = order.get('Order Type', 'Vial')
            qty = int(order.get('QTY', 0) or 0)
            
            if product_code in product_prices:
                if order_type == 'Kit':
                    total_kits_usd += product_prices[product_code]['kit_price'] * qty
                    total_kits_count += qty
                else:
                    total_vials_usd += product_prices[product_code]['vial_price'] * qty
                    total_vials_count += qty
        
        return {
            'total_kits_usd': total_kits_usd,
            'total_vials_usd': total_vials_usd,
            'total_kits_count': total_kits_count,
            'total_vials_count': total_vials_count,
            'combined_total_usd': total_kits_usd + total_vials_usd
        }
    except Exception as e:
        print(f"Error calculating order stats: {e}")
        import traceback
        traceback.print_exc()
        # Return default stats
        return {
            'total_kits_usd': 0.0,
            'total_vials_usd': 0.0,
            'total_kits_count': 0,
            'total_vials_count': 0,
            'combined_total_usd': 0.0
        }

def get_consolidated_order_stats():
    """Get consolidated order stats with caching"""
    return get_cached('order_stats', _fetch_consolidated_order_stats, cache_duration=120)  # 2 minutes

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
            stats = inventory.get(product['code'], {
                'total_vials': 0, 'kits_generated': 0, 'remaining_vials': 0,
                'slots_to_next_kit': VIALS_PER_KIT, 'max_kits': MAX_KITS_DEFAULT, 'is_locked': False,
                'vials_per_kit': VIALS_PER_KIT
            })
            product['inventory'] = stats
            if stats.get('total_vials', 0) > 0:
                products_with_orders.append(product)
        
        order_goal = get_order_goal()
        
        return render_template('index.html', 
                             products=products, 
                             products_with_orders=products_with_orders,
                             exchange_rate=exchange_rate,
                             admin_fee=ADMIN_FEE_PHP,
                             vials_per_kit=VIALS_PER_KIT,
                             order_form_locked=order_form_lock['is_locked'],
                             order_form_lock_message=order_form_lock['message'],
                             telegram_bot_username=TELEGRAM_BOT_USERNAME,
                             order_stats=order_stats,
                             order_goal=order_goal)
    except Exception as e:
        app.logger.error(f"Error loading index page: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Internal server error', 'details': str(e)}), 500

@app.route('/admin')
def admin_panel():
    """Admin panel for managing products and orders"""
    return render_template('admin.html')

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

@app.route('/api/admin/products')
def api_admin_products():
    """Get products with admin data"""
    products = get_products()
    inventory = get_inventory_stats()
    locks = get_product_locks()
    
    for product in products:
        code = product['code']
        inv = inventory.get(code, {'kits_generated': 0, 'total_vials': 0})
        lock = locks.get(code, {'max_kits': MAX_KITS_DEFAULT, 'is_locked': False})
        
        product['kits_generated'] = inv.get('kits_generated', 0)
        product['total_vials'] = inv.get('total_vials', 0)
        product['max_kits'] = lock.get('max_kits', MAX_KITS_DEFAULT)
        product['is_locked'] = lock.get('is_locked', False) or inv.get('kits_generated', 0) >= lock.get('max_kits', MAX_KITS_DEFAULT)
    
    return jsonify(products)

@app.route('/api/admin/lock-product', methods=['POST'])
def api_lock_product():
    """Lock/unlock a product"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    product_code = data.get('product_code')
    is_locked = data.get('is_locked', True)
    max_kits = data.get('max_kits')
    
    if set_product_lock(product_code, is_locked, max_kits):
        return jsonify({'success': True})
    return jsonify({'error': 'Failed to update'}), 500

@app.route('/api/admin/lock-order-form', methods=['POST'])
def api_lock_order_form():
    """Lock/unlock the entire order form"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    is_locked = data.get('is_locked', True)
    message = data.get('message', 'Orders are currently closed. Thank you for your patience!')
    
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

@app.route('/api/exchange-rate')
def api_exchange_rate():
    return jsonify({'rate': get_exchange_rate(), 'currency': 'PHP'})

@app.route('/api/products')
def api_products():
    products = get_products()
    inventory = get_inventory_stats()
    for product in products:
        vials_per_kit = product.get('vials_per_kit', VIALS_PER_KIT)
        product['inventory'] = inventory.get(product['code'], {
            'total_vials': 0, 'kits_generated': 0, 'remaining_vials': 0,
            'slots_to_next_kit': vials_per_kit, 'vials_per_kit': vials_per_kit, 'is_locked': False
        })
    return jsonify(products)

@app.route('/api/orders/lookup')
def api_orders_lookup():
    """Lookup orders by email or telegram"""
    email = request.args.get('email', '').lower().strip()
    telegram = request.args.get('telegram', '').lower().strip()
    
    if not email and not telegram:
        return jsonify([])
    
    orders = get_orders_from_sheets()
    
    # Normalize telegram username (remove @ if present for comparison)
    telegram_normalized = telegram.lstrip('@') if telegram else ''
    
    # Group by Order ID and filter by email/telegram
    grouped = {}
    for order in orders:
        order_id = order.get('Order ID', '')
        if not order_id:
            continue
        
        order_email = str(order.get('Email', '')).lower().strip()
        order_telegram = str(order.get('Telegram Username', '')).lower().strip()
        order_telegram_normalized = order_telegram.lstrip('@')
        
        # Match by email OR telegram
        matches = False
        if email and order_email and email == order_email:
            matches = True
        # Match telegram with or without @ symbol (exact match after normalization)
        if telegram_normalized and order_telegram_normalized:
            # Try exact match first
            if telegram_normalized == order_telegram_normalized:
                matches = True
            # Fallback to substring match for flexibility (user input contained in order telegram)
            elif telegram_normalized in order_telegram_normalized:
                matches = True
        
        if not matches:
            continue
            
        if order_id not in grouped:
            grouped[order_id] = {
                'order_id': order_id,
                'order_date': order.get('Order Date', ''),
                'full_name': order.get('Name', order.get('Full Name', '')),
                'email': order.get('Email', ''),
                'telegram': order.get('Telegram Username', ''),
                'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                'status': order.get('Order Status', 'Pending'),
                'payment_status': order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid')),
                'payment_screenshot': order.get('Link to Payment', order.get('Payment Screenshot Link', order.get('Payment Screenshot', ''))),
                'full_name': order.get('Full Name', order.get('Name', '')),
                'contact_number': order.get('Contact Number', ''),
                'mailing_address': order.get('Mailing Address', ''),
                'items': []
            }
        
        if order.get('Product Code'):
            grouped[order_id]['items'].append({
                'product_code': order.get('Product Code', ''),
                'product_name': order.get('Product Name', ''),
                'order_type': order.get('Order Type', 'Vial'),  # Default to 'Vial' if missing
                'qty': int(order.get('QTY', 0) or 0),
                'line_total_php': float(order.get('Line Total PHP', 0) or 0)
            })
    
    return jsonify(list(grouped.values()))

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
                'items': []
            }
        
        if order.get('Product Code'):
            grouped[order_id]['items'].append({
                'product_code': order.get('Product Code', ''),
                'product_name': order.get('Product Name', ''),
                'order_type': order.get('Order Type', ''),
                'qty': int(order.get('QTY', 0) or 0),
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
    """Submit new order"""
    data = request.json
    exchange_rate = get_exchange_rate()
    
    # Check for locked products
    inventory = get_inventory_stats()
    for item in data.get('items', []):
        code = item.get('product_code')
        if inventory.get(code, {}).get('is_locked'):
            return jsonify({
                'success': False,
                'error': f'Product {code} is currently locked and cannot be ordered'
            }), 400
    
    # Consolidate items with same product_code + order_type
    consolidated = {}
    for item in data.get('items', []):
        key = (item['product_code'], item.get('order_type', 'Vial'))
        if key in consolidated:
            consolidated[key]['qty'] += item['qty']
        else:
            consolidated[key] = {
                'product_code': item['product_code'],
                'order_type': item.get('order_type', 'Vial'),
                'qty': item['qty']
            }
    
    # Calculate totals
    total_usd = 0
    items_with_prices = []
    products = get_products()
    
    for key, item in consolidated.items():
        product = next((p for p in products if p['code'] == item['product_code']), None)
        if product:
            unit_price = product['kit_price'] if item.get('order_type') == 'Kit' else product['vial_price']
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
            total_usd += line_total_usd
    
    total_php = total_usd * exchange_rate
    grand_total_php = total_php + ADMIN_FEE_PHP
    
    order_data = {
        'full_name': data.get('full_name', ''),
        'email': data.get('email', ''),
        'telegram': data.get('telegram', ''),
        'items': items_with_prices,
        'exchange_rate': exchange_rate,
        'grand_total_php': grand_total_php
    }
    
    order_id = save_order_to_sheets(order_data)
    
    if order_id:
        # Send Telegram notification
        items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']}) - ₱{item['line_total_php']:.2f}" for item in items_with_prices])
        telegram_msg = f"""🛒 <b>New Order!</b>

<b>Order ID:</b> {order_id}
<b>Customer:</b> {order_data['full_name']}
<b>Telegram:</b> {order_data.get('telegram', 'N/A')}

<b>Items:</b>
{items_text}

<b>Grand Total:</b> ₱{grand_total_php:,.2f}
<b>Status:</b> Pending Payment"""
        send_telegram_notification(telegram_msg)
        
        # Also notify customer if registered
        notify_customer_order(order_data, order_id)
        
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
    
    return jsonify({'success': False, 'error': 'Failed to save order'}), 500

@app.route('/api/orders/<order_id>/add-items', methods=['POST'])
def api_add_items(order_id):
    """Add items to existing order"""
    order = get_order_by_id(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if order['locked']:
        return jsonify({'error': 'Order is locked'}), 403
    
    data = request.json
    items = data.get('items', [])
    
    # Calculate prices
    products = get_products()
    exchange_rate = order['exchange_rate']
    
    items_with_prices = []
    for item in items:
        product = next((p for p in products if p['code'] == item['product_code']), None)
        if product:
            unit_price = product['kit_price'] if item.get('order_type') == 'Kit' else product['vial_price']
            line_total_usd = unit_price * item['qty']
            
            items_with_prices.append({
                'product_code': item['product_code'],
                'product_name': product['name'],
                'order_type': item.get('order_type', 'Vial'),
                'qty': item['qty'],
                'unit_price_usd': unit_price,
                'line_total_usd': line_total_usd,
                'line_total_php': line_total_usd * exchange_rate
            })
    
    if add_items_to_order(order_id, items_with_prices, exchange_rate):
        return jsonify({'success': True})
    
    return jsonify({'error': 'Failed to add items'}), 500

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
        return jsonify({'success': True})
    
    return jsonify({'error': 'Failed to update item'}), 500

def update_item_quantity(order_id, product_code, order_type, new_qty):
    """Update quantity of a specific item in an order"""
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = spreadsheet.worksheet('PepHaul Entry')
        
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
def api_cancel_order(order_id):
    """Cancel an order and wipe quantities to reset inventory"""
    order = get_order_by_id(order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    
    if order['locked']:
        return jsonify({'error': 'Order is locked'}), 403
    
    # Wipe quantities for this order to reset inventory
    if wipe_order_quantities(order_id):
        if update_order_status(order_id, status='Cancelled'):
            return jsonify({'success': True})
    
    return jsonify({'error': 'Failed to cancel order'}), 500

def wipe_order_quantities(order_id):
    """Set all quantities to 0 for a cancelled order to reset inventory"""
    if not sheets_client:
        return False
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = spreadsheet.worksheet('PepHaul Entry')
        
        # Get all data
        all_values = worksheet.get_all_values()
        headers = all_values[0] if all_values else []
        
        # Find column indices
        col_order_id = headers.index('Order ID') if 'Order ID' in headers else 0
        col_qty = headers.index('QTY') if 'QTY' in headers else 8
        col_line_total_usd = headers.index('Line Total USD') if 'Line Total USD' in headers else 10
        col_line_total_php = headers.index('Line Total PHP') if 'Line Total PHP' in headers else 12
        col_admin_fee = headers.index('Admin Fee PHP') if 'Admin Fee PHP' in headers else 13
        col_grand_total = headers.index('Grand Total PHP') if 'Grand Total PHP' in headers else 14
        
        # Find all rows belonging to this order
        order_rows = []
        for row_num, row in enumerate(all_values[1:], start=2):  # Skip header
            if len(row) > col_order_id:
                # Check if this row belongs to the order (first row has order_id, subsequent have empty)
                if row[col_order_id] == order_id:
                    order_rows.append(row_num)
                elif order_rows and not row[col_order_id]:
                    # Continue adding rows if they're part of the same order (empty Order ID means continuation)
                    # Check if product code exists
                    if len(row) > 5 and row[5]:  # Product Code column
                        order_rows.append(row_num)
                elif order_rows and row[col_order_id]:
                    # New order started, stop
                    break
        
        # Also find rows by searching for order_id anywhere in first column (for added items)
        cells = worksheet.findall(order_id)
        for cell in cells:
            if cell.row not in order_rows:
                order_rows.append(cell.row)
        
        # Wipe quantities and totals for all order rows
        for row_num in order_rows:
            worksheet.update_cell(row_num, col_qty + 1, 0)  # QTY = 0
            worksheet.update_cell(row_num, col_line_total_usd + 1, 0)  # Line Total USD = 0
            worksheet.update_cell(row_num, col_line_total_php + 1, 0)  # Line Total PHP = 0
        
        # Wipe grand total on first row
        if order_rows:
            first_row = min(order_rows)
            worksheet.update_cell(first_row, col_admin_fee + 1, 0)
            worksheet.update_cell(first_row, col_grand_total + 1, 0)
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        return True
    except Exception as e:
        print(f"Error wiping order quantities: {e}")
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
        update_order_status(order_id, payment_status='Paid', payment_screenshot=drive_link)
        
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
    
    # Update order with payment link
    if update_order_status(order_id, payment_status='Paid', payment_screenshot=payment_link):
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
    """Mark payment as sent to GB Admin - updates status to Waiting for Confirmation"""
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

Customer has marked payment as sent to GB Admin.
⏳ Status: <b>Waiting for Confirmation</b>

Please check GCash and confirm payment in Admin Panel."""
            send_telegram_notification(telegram_msg)
        
        print(f"✅ Payment marked as sent - status updated to Waiting for Confirmation")
        return jsonify({'success': True, 'message': 'Payment marked as sent! GB Admin will be notified.'})
    
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
        update_order_status(order_id, payment_status='Paid', payment_screenshot=drive_link)
        
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
        worksheet = spreadsheet.worksheet('PepHaul Entry')
        
        # Find the order's first row
        cell = worksheet.find(order_id)
        if not cell:
            return jsonify({'error': 'Order not found'}), 404
        
        # Get headers to find mailing address columns
        headers = worksheet.row_values(1)
        
        # Find mailing columns (using correct column names)
        mailing_name_col = None
        mailing_phone_col = None
        mailing_address_col = None
        
        for i, header in enumerate(headers):
            if header == 'Full Name':
                mailing_name_col = i + 1
            elif header == 'Contact Number':
                mailing_phone_col = i + 1
            elif header == 'Mailing Address':
                mailing_address_col = i + 1
        
        # If columns don't exist, add them (shouldn't happen if headers are correct, but handle gracefully)
        if mailing_name_col is None:
            mailing_name_col = len(headers) + 1
            worksheet.update_cell(1, mailing_name_col, 'Full Name')
        if mailing_phone_col is None:
            mailing_phone_col = len(headers) + 2 if mailing_name_col == len(headers) + 1 else len(headers) + 1
            worksheet.update_cell(1, mailing_phone_col, 'Contact Number')
        if mailing_address_col is None:
            next_col = max(mailing_name_col, mailing_phone_col) + 1
            worksheet.update_cell(1, next_col, 'Mailing Address')
            mailing_address_col = next_col
        
        # Update the order row with mailing info
        worksheet.update_cell(cell.row, mailing_name_col, mailing_name)
        worksheet.update_cell(cell.row, mailing_phone_col, mailing_phone)
        worksheet.update_cell(cell.row, mailing_address_col, mailing_address)
        
        # Clear cache since orders changed
        clear_cache('orders')
        clear_cache('inventory')
        clear_cache('order_stats')
        
        # Send notification to admin
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
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error saving mailing address: {e}")
        return jsonify({'error': str(e)}), 500

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
                    print(f"✅ GB Admin registered: @{username} (chat_id: {chat_id})")
            
            # Send welcome message
            if is_admin:
                welcome_msg = f"""🎉 <b>Welcome GB Admin, {first_name}!</b> 👑

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
    """Send order confirmation to customer via Telegram if registered"""
    telegram_handle = order_data.get('telegram', '').strip().lower()
    if not telegram_handle:
        return False
    
    # Clean up the handle
    if telegram_handle.startswith('@'):
        telegram_handle = telegram_handle[1:]
    
    chat_id = telegram_customers.get(telegram_handle) or telegram_customers.get(f"@{telegram_handle}")
    
    if not chat_id:
        print(f"Customer @{telegram_handle} not registered for Telegram notifications")
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

@app.route('/api/admin/orders')
def api_admin_orders():
    """Get all orders for admin panel"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    orders = get_orders_from_sheets()
    
    # Group by Order ID with full details
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
                'email': order.get('Email', ''),
                'telegram': order.get('Telegram Username', ''),
                'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                'status': order.get('Order Status', 'Pending'),
                'locked': str(order.get('Locked', 'No')).lower() == 'yes',
                'payment_status': order.get('Payment Status', order.get('Confirmed Paid?', 'Unpaid')),
                'payment_screenshot': order.get('Link to Payment', order.get('Payment Screenshot Link', order.get('Payment Screenshot', ''))),
                'full_name': order.get('Full Name', order.get('Name', '')),
                'contact_number': order.get('Contact Number', ''),
                'mailing_address': order.get('Mailing Address', ''),
                'items': []
            }
        
        if order.get('Product Code'):
            grouped[order_id]['items'].append({
                'product_code': order.get('Product Code', ''),
                'product_name': order.get('Product Name', ''),
                'order_type': order.get('Order Type', ''),
                'qty': int(order.get('QTY', 0) or 0),
                'unit_price_usd': float(order.get('Unit Price USD', 0) or 0),
                'line_total_php': float(order.get('Line Total PHP', 0) or 0)
            })
    
    # Sort by date (newest first)
    sorted_orders = sorted(grouped.values(), key=lambda x: x['order_date'], reverse=True)
    return jsonify(sorted_orders)

@app.route('/api/admin/orders/<order_id>/confirm-payment', methods=['POST'])
def api_admin_confirm_payment(order_id):
    """Admin: Confirm payment for an order"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if update_order_status(order_id, payment_status='Paid'):
        # Get order details for notifications
        order = get_order_by_id(order_id)
        if order:
            items_text = '\n'.join([f"• {item['product_name']} ({item['order_type']} x{item['qty']})" for item in order.get('items', [])])
            
            # Notify GB Admin via Telegram
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

@app.route('/api/admin/confirm-payment', methods=['POST'])
def api_admin_confirm_payment_post():
    """Admin: Confirm payment for an order (POST with body)"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    order_id = data.get('order_id')
    
    if not order_id:
        return jsonify({'error': 'Order ID required'}), 400
    
    if update_order_status(order_id, payment_status='Paid'):
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

@app.route('/api/admin/refresh-pephauler-orders', methods=['POST'])
def api_refresh_pephauler_orders():
    """Admin: Refresh the PepHauler Orders tab"""
    if not session.get('is_admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if populate_pephauler_orders_tab():
        return jsonify({'success': True, 'message': 'PepHauler Orders tab refreshed successfully'})
    return jsonify({'error': 'Failed to refresh PepHauler Orders tab'}), 500

# Initialize on startup
init_google_services()
ensure_worksheets_exist()
# Populate PepHauler Orders tab after ensuring it exists
populate_pephauler_orders_tab()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=os.getenv('FLASK_DEBUG', 'true').lower() == 'true', host='0.0.0.0', port=port)
