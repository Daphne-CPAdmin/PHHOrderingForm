"""
PepHaul Order Form - Web Application
Full order management with payment tracking and admin controls
"""

from flask import Flask, render_template, request, jsonify, session
import requests
import json
import os
import base64
from datetime import datetime
from dotenv import load_dotenv
from collections import defaultdict
from functools import wraps
import secrets

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
        
        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            sheets_client = gspread.authorize(creds)
            drive_service = build('drive', 'v3', credentials=creds)
            print("Google services initialized from environment variable")
        elif os.path.exists('credentials.json'):
            creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
            sheets_client = gspread.authorize(creds)
            drive_service = build('drive', 'v3', credentials=creds)
            print("Google services initialized from credentials.json")
        else:
            print("No Google credentials found")
            
    except Exception as e:
        print(f"Error initializing Google services: {e}")

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
                'Order ID', 'Order Date', 'Full Name', 'Email', 'Telegram Username',
                'Product Code', 'Product Name', 'Order Type', 'QTY', 'Unit Price USD',
                'Line Total USD', 'Exchange Rate', 'Line Total PHP', 'Admin Fee PHP',
                'Grand Total PHP', 'Order Status', 'Locked', 'Confirmed Paid?', 
                'Payment Screenshot', 'Payment Date', 'Notes'
            ]
            worksheet.update('A1:U1', [headers])
        
        # Product Locks tab (for admin)
        if 'Product Locks' not in existing_sheets:
            worksheet = spreadsheet.add_worksheet(title='Product Locks', rows=200, cols=5)
            headers = ['Product Code', 'Max Kits', 'Is Locked', 'Locked Date', 'Locked By']
            worksheet.update('A1:E1', [headers])
            
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

def get_order_form_lock():
    """Get order form lock status"""
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
            
            return True
        except Exception as e:
            print(f"Error setting order form lock: {e}")
            return False
    
    return True

def get_orders_from_sheets():
    """Read existing orders from PepHaul Entry tab"""
    if not sheets_client:
        return []
    
    try:
        spreadsheet = sheets_client.open_by_key(GOOGLE_SHEETS_ID)
        worksheet = spreadsheet.worksheet('PepHaul Entry')
        records = worksheet.get_all_records()
        return records
    except Exception as e:
        print(f"Error reading orders: {e}")
        return []

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
        'full_name': first_item.get('Full Name', ''),
        'email': first_item.get('Email', ''),
        'telegram': first_item.get('Telegram Username', ''),
        'exchange_rate': float(first_item.get('Exchange Rate', FALLBACK_EXCHANGE_RATE) or FALLBACK_EXCHANGE_RATE),
        'admin_fee_php': float(first_item.get('Admin Fee PHP', ADMIN_FEE_PHP) or 0),
        'grand_total_php': float(first_item.get('Grand Total PHP', 0) or 0),
        'status': first_item.get('Order Status', 'Pending'),
        'locked': str(first_item.get('Locked', 'No')).lower() == 'yes',
        'payment_status': first_item.get('Confirmed Paid?', first_item.get('Payment Status', 'Unpaid')),
        'payment_screenshot': first_item.get('Payment Screenshot', ''),
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
                order_data['full_name'],            # All rows have Full Name
                order_data['email'],                # All rows have Email
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
                'Unpaid' if i == 0 else '',                  # Only first row (Confirmed Paid?)
                '',                                          # Payment Screenshot - only first row
                '',                                          # Payment Date
                ''                                           # Notes
            ]
            rows_to_add.append(row)
        
        if rows_to_add:
            end_row = next_row + len(rows_to_add) - 1
            worksheet.update(f'A{next_row}:U{end_row}', rows_to_add)
        
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
                worksheet.update_cell(row, 18, payment_status)
            if payment_screenshot:
                worksheet.update_cell(row, 19, payment_screenshot)
                worksheet.update_cell(row, 20, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
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
            order_info = {'full_name': '', 'email': '', 'telegram': '', 'order_date': ''}
            col_full_name = headers.index('Full Name') if 'Full Name' in headers else 2
            col_email = headers.index('Email') if 'Email' in headers else 3
            col_telegram = headers.index('Telegram Username') if 'Telegram Username' in headers else 4
            col_order_date = headers.index('Order Date') if 'Order Date' in headers else 1
            
            for row in all_values[1:]:
                if len(row) > col_indices['order_id'] and row[col_indices['order_id']] == order_id:
                    order_info['full_name'] = row[col_full_name] if len(row) > col_full_name else ''
                    order_info['email'] = row[col_email] if len(row) > col_email else ''
                    order_info['telegram'] = row[col_telegram] if len(row) > col_telegram else ''
                    order_info['order_date'] = row[col_order_date] if len(row) > col_order_date else ''
                    break
            
            rows_to_add = []
            for item in items_to_add:
                row = [
                    order_id,                           # All rows have Order ID
                    order_info['order_date'],           # All rows have Order Date
                    order_info['full_name'],            # All rows have Full Name
                    order_info['email'],                # All rows have Email
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
                    '',                                 # Confirmed Paid? - only on first row
                    '',                                 # Payment Screenshot
                    '',                                 # Payment Date
                    f'Added to {order_id}'              # Notes
                ]
                rows_to_add.append(row)
            
            end_row = next_row + len(rows_to_add) - 1
            worksheet.update(f'A{next_row}:U{end_row}', rows_to_add)
        
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

def upload_to_drive(file_data, filename, order_id):
    """Upload payment screenshot to Google Drive"""
    if not drive_service:
        print("Drive service not initialized - check GOOGLE_CREDENTIALS_JSON env variable")
        return None
    
    try:
        from googleapiclient.http import MediaInMemoryUpload
        
        # Use the specific PepHaul Payments folder in Google Drive
        # Folder: https://drive.google.com/drive/folders/1HOt6b11IWp9CIazujHJMkbyCxQSrwFgg
        folder_id = os.getenv('PAYMENT_DRIVE_FOLDER_ID', '1HOt6b11IWp9CIazujHJMkbyCxQSrwFgg')
        
        print(f"Uploading to folder: {folder_id}")
        
        # Decode base64 if needed
        if ',' in file_data:
            file_data = file_data.split(',')[1]
        
        file_bytes = base64.b64decode(file_data)
        
        # Detect mime type from data
        mime_type = 'image/jpeg'
        if file_data.startswith('/9j/'):
            mime_type = 'image/jpeg'
        elif file_data.startswith('iVBOR'):
            mime_type = 'image/png'
        elif file_data.startswith('R0lGO'):
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
        
        print(f"File created with ID: {file.get('id')}")
        
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
        print(f"Error uploading to Drive: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_inventory_stats():
    """Calculate inventory statistics with product-specific vials per kit"""
    orders = get_orders_from_sheets()
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

def get_products():
    """Get complete product list with vials per kit"""
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
        {"code": "LC120", "name": "Lipo-C 120mg (Methionine/Choline/Carnitine)", "kit_price": 60, "vial_price": 6.0, "vials_per_kit": 10},
        {"code": "LC216", "name": "Lipo-B 216mg (Carnitine/Arginine/B-Complex)", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "LC425", "name": "Lipo-C FOCUS (ATP/Eria Jarensis/Carnitine)", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "LC500", "name": "L-Carnitine 500mg", "kit_price": 65, "vial_price": 6.5, "vials_per_kit": 10},
        {"code": "LC526", "name": "Lipo-C FAT BLASTER (Carnitine/MIC/B12/NADH)", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "LC553", "name": "SUPER SHRED (Carnitine/MIC/ATP/Albuterol)", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "RP226", "name": "Relaxation PM (Gaba/Melatonin/Arginine)", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "SHB", "name": "SUPER Human Blend (Multi Amino Complex)", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "HHB", "name": "Healthy Hair Skin Nails Blend (B-Complex)", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "LMX", "name": "Lipo Mino Mix (B-Complex/Carnitine)", "kit_price": 95, "vial_price": 9.5, "vials_per_kit": 10},
        {"code": "GAZ", "name": "Immunological Enhancement (Glutathione/Zinc)", "kit_price": 135, "vial_price": 13.5, "vials_per_kit": 10},
        {"code": "SHR", "name": "SHRED (Carnitine/B12/MIC)", "kit_price": 105, "vial_price": 10.5, "vials_per_kit": 10},
        {"code": "GGH", "name": "GHK-CU + Glutathione + Histidine + NADH", "kit_price": 115, "vial_price": 11.5, "vials_per_kit": 10},
        {"code": "SZ352", "name": "Sleep Blend (Gaba/Theanine/Melatonin)", "kit_price": 105, "vial_price": 10.5, "vials_per_kit": 10},
        # Vitamins
        {"code": "D320", "name": "D320 (vitamins)", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
        {"code": "B1201", "name": "B12 (small)", "kit_price": 40, "vial_price": 4.0, "vials_per_kit": 10},
        {"code": "B1210", "name": "B12 (large)", "kit_price": 75, "vial_price": 7.5, "vials_per_kit": 10},
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

# Routes
@app.route('/')
def index():
    """Main order form page"""
    exchange_rate = get_exchange_rate()
    products = get_products()
    inventory = get_inventory_stats()
    order_form_lock = get_order_form_lock()
    
    for product in products:
        stats = inventory.get(product['code'], {
            'total_vials': 0, 'kits_generated': 0, 'remaining_vials': 0,
            'slots_to_next_kit': VIALS_PER_KIT, 'max_kits': MAX_KITS_DEFAULT, 'is_locked': False
        })
        product['inventory'] = stats
    
    return render_template('index.html', 
                         products=products, 
                         exchange_rate=exchange_rate,
                         admin_fee=ADMIN_FEE_PHP,
                         vials_per_kit=VIALS_PER_KIT,
                         order_form_locked=order_form_lock['is_locked'],
                         order_form_lock_message=order_form_lock['message'])

@app.route('/admin')
def admin_panel():
    """Admin panel for managing products and orders"""
    return render_template('admin.html')

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
    
    # Group by Order ID and filter by email/telegram
    grouped = {}
    for order in orders:
        order_id = order.get('Order ID', '')
        if not order_id:
            continue
        
        order_email = str(order.get('Email', '')).lower().strip()
        order_telegram = str(order.get('Telegram Username', '')).lower().strip()
        
        # Match by email OR telegram
        matches = False
        if email and order_email and email == order_email:
            matches = True
        if telegram and order_telegram and telegram in order_telegram:
            matches = True
        
        if not matches:
            continue
            
        if order_id not in grouped:
            grouped[order_id] = {
                'order_id': order_id,
                'order_date': order.get('Order Date', ''),
                'full_name': order.get('Full Name', ''),
                'email': order.get('Email', ''),
                'telegram': order.get('Telegram Username', ''),
                'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                'status': order.get('Order Status', 'Pending'),
                'payment_status': order.get('Confirmed Paid?', order.get('Payment Status', 'Unpaid')),
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
                'full_name': order.get('Full Name', ''),
                'email': order.get('Email', ''),
                'telegram': order.get('Telegram Username', ''),
                'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                'status': order.get('Order Status', 'Pending'),
                'locked': str(order.get('Locked', 'No')).lower() == 'yes',
                'payment_status': order.get('Confirmed Paid?', order.get('Payment Status', 'Unpaid')),
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
            
        name = str(order.get('Full Name', '')).lower()
        email = str(order.get('Email', '')).lower()
        
        if query in name or query in email or query in order_id.lower():
            if order_id not in matching:
                matching[order_id] = {
                    'order_id': order_id,
                    'full_name': order.get('Full Name', ''),
                    'email': order.get('Email', ''),
                    'status': order.get('Order Status', 'Pending'),
                    'payment_status': order.get('Confirmed Paid?', order.get('Payment Status', 'Unpaid')),
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
<b>Email:</b> {order_data['email']}
<b>Telegram:</b> {order_data.get('telegram', 'N/A')}

<b>Items:</b>
{items_text}

<b>Grand Total:</b> ₱{grand_total_php:,.2f}
<b>Status:</b> Pending Payment"""
        send_telegram_notification(telegram_msg)
        
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
    data = request.json
    screenshot_data = data.get('screenshot')
    
    if not screenshot_data:
        return jsonify({'error': 'No screenshot provided'}), 400
    
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
        
        return jsonify({'success': True, 'link': drive_link})
    
    return jsonify({'error': 'Failed to upload'}), 500

@app.route('/api/upload-payment', methods=['POST'])
def api_upload_payment_generic():
    """Upload payment screenshot (generic endpoint)"""
    data = request.json
    order_id = data.get('order_id')
    file_data = data.get('file_data')
    file_name = data.get('file_name', 'payment.jpg')
    
    if not order_id:
        return jsonify({'error': 'No order ID provided'}), 400
    
    if not file_data:
        return jsonify({'error': 'No file data provided'}), 400
    
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
        
        return jsonify({'success': True, 'link': drive_link})
    
    return jsonify({'error': 'Failed to upload - Drive service may not be configured'}), 500

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
                'full_name': order.get('Full Name', ''),
                'email': order.get('Email', ''),
                'telegram': order.get('Telegram Username', ''),
                'grand_total_php': float(order.get('Grand Total PHP', 0) or 0),
                'status': order.get('Order Status', 'Pending'),
                'locked': str(order.get('Locked', 'No')).lower() == 'yes',
                'payment_status': order.get('Confirmed Paid?', order.get('Payment Status', 'Unpaid')),
                'payment_screenshot': order.get('Payment Screenshot', ''),
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

# Initialize on startup
init_google_services()
ensure_worksheets_exist()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=os.getenv('FLASK_DEBUG', 'true').lower() == 'true', host='0.0.0.0', port=port)
