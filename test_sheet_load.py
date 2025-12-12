import gspread
from google.oauth2.service_account import Credentials
import json

# Load credentials
with open('pephaul-order-form-credentials.json', 'r') as f:
    creds_data = json.load(f)

# Set up credentials
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
creds = Credentials.from_service_account_info(creds_data, scopes=SCOPES)
client = gspread.authorize(creds)

# Open spreadsheet
SHEET_ID = '18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s'
spreadsheet = client.open_by_key(SHEET_ID)

# List all worksheets
print("Available worksheets:")
for ws in spreadsheet.worksheets():
    print(f"  - {ws.title}")

# Try to open Price List
try:
    worksheet = spreadsheet.worksheet('Price List')
    records = worksheet.get_all_records()
    print(f"\n✅ Found 'Price List' tab with {len(records)} rows")
    if len(records) > 0:
        print(f"\nFirst record:")
        print(json.dumps(records[0], indent=2))
        print(f"\nColumn headers:")
        print(list(records[0].keys()))
except Exception as e:
    print(f"\n❌ Error loading 'Price List' tab: {e}")
