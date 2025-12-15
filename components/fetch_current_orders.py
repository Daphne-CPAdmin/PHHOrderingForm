"""
Component: Fetch Current Orders from Google Sheets
Reads orders from PepHaul Entry tab and saves to CSV
"""

import pandas as pd
import logging
from datetime import datetime
import sys
import os
import gspread

# Add parent directory to path to import data_sources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_sources import DataConnector

# Setup logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('logs/audit_log.txt', mode='a'),
        logging.StreamHandler()
    ]
)

def run(input_file, output_file, config={}):
    """
    Fetch current orders from Google Sheets
    
    Args:
        input_file: Google Sheets URL with PepHaul Entry tab (or spreadsheet ID)
        output_file: Path to save CSV file (e.g., "data/output/current_orders.csv")
        config: Optional config dict (uses GOOGLE_SHEETS_ID and GOOGLE_CREDENTIALS_JSON from env)
    """
    logger = logging.getLogger(__name__)
    connector = DataConnector(config)
    
    # Start logging
    logger.info("="*50)
    logger.info("STARTING: fetch_current_orders")
    logger.info(f"INPUT: {input_file}")
    logger.info(f"OUTPUT: {output_file}")
    
    try:
        # Get Google Sheets ID from config or environment
        sheets_id = config.get('GOOGLE_SHEETS_ID') or os.getenv('GOOGLE_SHEETS_ID')
        
        if not sheets_id:
            raise ValueError("GOOGLE_SHEETS_ID not found in config or environment variables")
        
        # Construct Google Sheets URL if input_file is just an ID
        if not input_file.startswith('http'):
            # Assume it's a spreadsheet ID, construct URL
            sheets_url = f"https://docs.google.com/spreadsheets/d/{input_file}/edit#gid=0"
        else:
            sheets_url = input_file
        
        logger.info(f"Reading from Google Sheets: {sheets_id}")
        
        # Read from Google Sheets
        # Note: We need to read from the specific "PepHaul Entry" tab
        # DataConnector reads first sheet by default, so we'll handle tab selection manually
        if not connector.sheets_client:
            raise ValueError("Google Sheets client not initialized. Set GOOGLE_CREDENTIALS_JSON environment variable.")
        
        spreadsheet = connector.sheets_client.open_by_key(sheets_id)
        
        # Find PepHaul Entry worksheet
        try:
            worksheet = spreadsheet.worksheet('PepHaul Entry')
            logger.info("Found 'PepHaul Entry' worksheet")
        except gspread.exceptions.WorksheetNotFound:
            logger.warning("'PepHaul Entry' worksheet not found, using first worksheet")
            worksheet = spreadsheet.sheet1
        
        # Get all records
        records = worksheet.get_all_records()
        logger.info(f"Fetched {len(records)} rows from Google Sheets")
        
        if len(records) == 0:
            logger.warning("No orders found in sheet")
            # Create empty DataFrame with expected columns
            df = pd.DataFrame(columns=[
                'Order ID', 'Order Date', 'Name', 'Telegram Username',
                'Product Code', 'Product Name', 'Order Type', 'QTY', 'Unit Price USD',
                'Line Total USD', 'Exchange Rate', 'Line Total PHP', 'Admin Fee PHP',
                'Grand Total PHP', 'Order Status', 'Locked', 'Payment Status', 
                'Remarks', 'Link to Payment', 'Payment Date', 'Full Name', 'Contact Number', 'Mailing Address'
            ])
        else:
            df = pd.DataFrame(records)
            logger.info(f"Columns: {', '.join(df.columns)}")
        
        # Create snapshot
        os.makedirs('data/temp', exist_ok=True)
        snapshot = f"data/temp/orders_snapshot_{datetime.now():%Y%m%d_%H%M%S}.csv"
        df.to_csv(snapshot, index=False)
        logger.info(f"Snapshot saved: {snapshot}")
        
        # Save to output file
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
        df.to_csv(output_file, index=False)
        logger.info(f"Saved {len(df)} rows to {output_file}")
        
        # Log summary
        if len(df) > 0:
            # Count unique orders
            if 'Order ID' in df.columns:
                unique_orders = df['Order ID'].nunique()
                logger.info(f"Found {unique_orders} unique orders")
            
            # Show order status breakdown if available
            if 'Order Status' in df.columns:
                status_counts = df['Order Status'].value_counts()
                logger.info(f"Order status breakdown: {dict(status_counts)}")
            
            # Show payment status breakdown if available
            if 'Payment Status' in df.columns:
                payment_counts = df['Payment Status'].value_counts()
                logger.info(f"Payment status breakdown: {dict(payment_counts)}")
        
        logger.info("SUMMARY: Successfully fetched orders")
        logger.info("COMPLETED: fetch_current_orders")
        logger.info("="*50)
        
        return True
        
    except Exception as e:
        logger.error(f"Error fetching orders: {e}")
        import traceback
        traceback.print_exc()
        logger.info("COMPLETED: fetch_current_orders (with errors)")
        logger.info("="*50)
        raise


if __name__ == '__main__':
    # Allow running component independently for testing
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Get Google Sheets ID from environment
    sheets_id = os.getenv('GOOGLE_SHEETS_ID', '18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s')
    
    run(
        input_file=sheets_id,
        output_file="data/output/current_orders.csv",
        config={'GOOGLE_SHEETS_ID': sheets_id}
    )

