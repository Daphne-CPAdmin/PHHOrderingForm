"""
Unified Workflow - PepHaul Order Management
Connects all automation components together
"""

import sys
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add components directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'components'))

# Import components
import fetch_current_orders
import test_google_sheets_connection

# Get values from .env file
GOOGLE_SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID', '18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s')

if __name__ == '__main__':
    print("="*60)
    print("PepHaul Order Management Workflow")
    print("="*60)
    
    # Step 0: Test Google Sheets connection (diagnostic)
    print("\n🔍 Step 0: Testing Google Sheets connection...")
    try:
        test_google_sheets_connection.run(
            input_file=GOOGLE_SHEETS_ID,
            output_file="data/output/connection_test_report.txt",
            config={'GOOGLE_SHEETS_ID': GOOGLE_SHEETS_ID}
        )
        print("✅ Connection test completed - check data/output/connection_test_report.txt")
    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        print("   Check Railway environment variables and service account permissions")
    
    # Step 1: Fetch current orders from Google Sheets
    print("\n📋 Step 1: Fetching current orders from Google Sheets...")
    try:
        fetch_current_orders.run(
            input_file=GOOGLE_SHEETS_ID,
            output_file="data/output/current_orders.csv",
            config={'GOOGLE_SHEETS_ID': GOOGLE_SHEETS_ID}
        )
        print("✅ Orders fetched successfully")
    except Exception as e:
        print(f"❌ Failed to fetch orders: {e}")
        print("   Check connection test report above")
    
    print("\n✅ Workflow completed!")
    print("📁 Check data/output/current_orders.csv for results")
    print("📁 Check data/output/connection_test_report.txt for diagnostics")
    print("📋 Check logs/audit_log.txt for detailed logs")
    print("="*60)

