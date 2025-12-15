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

# Get values from .env file
GOOGLE_SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID', '18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s')

if __name__ == '__main__':
    print("="*60)
    print("PepHaul Order Management Workflow")
    print("="*60)
    
    # Step 1: Fetch current orders from Google Sheets
    print("\n📋 Step 1: Fetching current orders from Google Sheets...")
    fetch_current_orders.run(
        input_file=GOOGLE_SHEETS_ID,
        output_file="data/output/current_orders.csv",
        config={'GOOGLE_SHEETS_ID': GOOGLE_SHEETS_ID}
    )
    
    print("\n✅ Workflow completed!")
    print("📁 Check data/output/current_orders.csv for results")
    print("📋 Check logs/audit_log.txt for detailed logs")
    print("="*60)

