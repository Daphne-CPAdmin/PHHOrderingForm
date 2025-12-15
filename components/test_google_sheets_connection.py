"""
Component: Test Google Sheets Connection
Diagnostic component to verify Google Sheets access on Railway
"""

import sys
import os
import logging
from datetime import datetime

# Add parent directory to path
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
    Test Google Sheets connection and access to PepHaul Entry tab
    
    Args:
        input_file: Google Sheets ID or URL
        output_file: Path to save diagnostic report
        config: Optional config dict
    """
    logger = logging.getLogger(__name__)
    
    logger.info("="*50)
    logger.info("STARTING: test_google_sheets_connection")
    logger.info(f"INPUT: {input_file}")
    logger.info(f"OUTPUT: {output_file}")
    
    try:
        # Get Google Sheets ID
        sheets_id = config.get('GOOGLE_SHEETS_ID') or os.getenv('GOOGLE_SHEETS_ID')
        if not sheets_id:
            # Try to extract from URL
            if 'spreadsheets/d/' in str(input_file):
                import re
                match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', str(input_file))
                if match:
                    sheets_id = match.group(1)
        
        if not sheets_id:
            raise ValueError("GOOGLE_SHEETS_ID not found")
        
        logger.info(f"Testing connection to Google Sheets: {sheets_id}")
        
        # Initialize connector
        connector = DataConnector(config)
        
        if not connector.sheets_client:
            logger.error("❌ Google Sheets client not initialized!")
            logger.error("   Check: GOOGLE_CREDENTIALS_JSON environment variable is set")
            raise ValueError("Google Sheets client not initialized")
        
        logger.info("✅ Google Sheets client initialized")
        
        # Try to open spreadsheet
        try:
            spreadsheet = connector.sheets_client.open_by_key(sheets_id)
            logger.info(f"✅ Successfully opened spreadsheet: {sheets_id}")
        except Exception as e:
            logger.error(f"❌ Failed to open spreadsheet: {e}")
            logger.error("   Check: Service account has access to this spreadsheet")
            raise
        
        # List all worksheets
        try:
            all_worksheets = spreadsheet.worksheets()
            worksheet_titles = [ws.title for ws in all_worksheets]
            logger.info(f"✅ Found {len(worksheet_titles)} worksheets: {worksheet_titles}")
        except Exception as e:
            logger.error(f"❌ Failed to list worksheets: {e}")
            raise
        
        # Try to access PepHaul Entry worksheet
        pephaul_found = False
        pephaul_worksheet = None
        
        for ws in all_worksheets:
            if ws.title == 'PepHaul Entry':
                pephaul_found = True
                pephaul_worksheet = ws
                logger.info(f"✅ Found 'PepHaul Entry' worksheet (gid: {ws.id})")
                break
        
        if not pephaul_found:
            logger.warning("⚠️ 'PepHaul Entry' worksheet not found!")
            logger.warning(f"   Available worksheets: {worksheet_titles}")
            if worksheet_titles:
                logger.info(f"   Using first worksheet: {worksheet_titles[0]}")
                pephaul_worksheet = all_worksheets[0]
            else:
                raise ValueError("No worksheets found in spreadsheet")
        
        # Try to read data
        try:
            all_values = pephaul_worksheet.get_all_values()
            logger.info(f"✅ Successfully read {len(all_values)} rows from worksheet")
            
            if len(all_values) > 0:
                headers = all_values[0]
                logger.info(f"✅ Headers found: {headers[:10]}...")
                logger.info(f"✅ Data rows: {len(all_values) - 1}")
            else:
                logger.warning("⚠️ Worksheet is empty (no headers or data)")
        except Exception as e:
            logger.error(f"❌ Failed to read data: {e}")
            raise
        
        # Try to get records
        try:
            records = pephaul_worksheet.get_all_records()
            logger.info(f"✅ Successfully parsed {len(records)} records")
            
            if len(records) > 0:
                logger.info(f"✅ Sample record keys: {list(records[0].keys())[:10]}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to parse records: {e}")
            logger.warning("   This might be okay if headers are malformed")
        
        # Write diagnostic report
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
        with open(output_file, 'w') as f:
            f.write(f"Google Sheets Connection Test Report\n")
            f.write(f"Generated: {datetime.now()}\n\n")
            f.write(f"Spreadsheet ID: {sheets_id}\n")
            f.write(f"Connection Status: ✅ SUCCESS\n")
            f.write(f"Worksheets Found: {len(worksheet_titles)}\n")
            f.write(f"Worksheet Titles: {', '.join(worksheet_titles)}\n")
            f.write(f"PepHaul Entry Found: {'✅ YES' if pephaul_found else '❌ NO'}\n")
            if pephaul_worksheet:
                f.write(f"PepHaul Entry GID: {pephaul_worksheet.id}\n")
            f.write(f"Rows in Worksheet: {len(all_values)}\n")
            f.write(f"Data Rows: {len(all_values) - 1 if len(all_values) > 0 else 0}\n")
            if len(all_values) > 0:
                f.write(f"Headers: {', '.join(all_values[0][:10])}...\n")
        
        logger.info(f"✅ Diagnostic report saved: {output_file}")
        logger.info("COMPLETED: test_google_sheets_connection")
        logger.info("="*50)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Connection test failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Write error report
        os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
        with open(output_file, 'w') as f:
            f.write(f"Google Sheets Connection Test Report\n")
            f.write(f"Generated: {datetime.now()}\n\n")
            f.write(f"Status: ❌ FAILED\n")
            f.write(f"Error: {str(e)}\n")
        
        logger.info("COMPLETED: test_google_sheets_connection (with errors)")
        logger.info("="*50)
        raise


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    sheets_id = os.getenv('GOOGLE_SHEETS_ID', '18Q3A7pmgj7WNi3GL8cgoLiD1gPmxGu_rMqzM3ohBo5s')
    
    run(
        input_file=sheets_id,
        output_file="data/output/connection_test_report.txt",
        config={'GOOGLE_SHEETS_ID': sheets_id}
    )

