"""
DataConnector - Helper class for Google Sheets and API operations
Handles reading/writing to Google Sheets and fetching from APIs
"""

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import os
import re
from urllib.parse import urlparse, parse_qs
import requests


class DataConnector:
    """Handles data connections to Google Sheets and APIs"""
    
    def __init__(self, config={}):
        """Initialize connector with optional config dict"""
        self.config = config
        self.sheets_client = None
        self._init_google_sheets()
    
    def _init_google_sheets(self):
        """Initialize Google Sheets client if credentials available"""
        try:
            creds_json = os.getenv('GOOGLE_CREDENTIALS_JSON')
            if creds_json:
                scopes = [
                    'https://www.googleapis.com/auth/spreadsheets',
                    'https://www.googleapis.com/auth/drive',
                    'https://www.googleapis.com/auth/drive.file'
                ]
                creds_dict = json.loads(creds_json)
                creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
                self.sheets_client = gspread.authorize(creds)
        except Exception as e:
            print(f"Warning: Could not initialize Google Sheets client: {e}")
    
    def _parse_sheets_url(self, url):
        """Extract spreadsheet ID and gid from Google Sheets URL"""
        # Handle different URL formats
        # https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={GID}
        # https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit?gid={GID}
        
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
        if not match:
            raise ValueError(f"Could not extract spreadsheet ID from URL: {url}")
        
        spreadsheet_id = match.group(1)
        
        # Extract gid (worksheet ID)
        gid = None
        if '#gid=' in url:
            gid_match = re.search(r'#gid=(\d+)', url)
            if gid_match:
                gid = int(gid_match.group(1))
        elif 'gid=' in url:
            gid_match = re.search(r'[?&]gid=(\d+)', url)
            if gid_match:
                gid = int(gid_match.group(1))
        
        return spreadsheet_id, gid
    
    def read_from_sheets(self, url):
        """Read data from Google Sheets URL
        
        Args:
            url: Google Sheets URL (e.g., https://docs.google.com/spreadsheets/d/.../edit#gid=0)
        
        Returns:
            pandas DataFrame
        """
        if not self.sheets_client:
            raise ValueError("Google Sheets client not initialized. Set GOOGLE_CREDENTIALS_JSON environment variable.")
        
        spreadsheet_id, gid = self._parse_sheets_url(url)
        spreadsheet = self.sheets_client.open_by_key(spreadsheet_id)
        
        if gid is not None:
            # Open specific worksheet by gid
            worksheet = spreadsheet.get_worksheet_by_id(gid)
        else:
            # Use first worksheet
            worksheet = spreadsheet.sheet1
        
        # Get all records as DataFrame
        records = worksheet.get_all_records()
        df = pd.DataFrame(records)
        
        return df
    
    def write_to_sheets(self, df, url):
        """Write DataFrame to Google Sheets
        
        Args:
            df: pandas DataFrame to write
            url: Google Sheets URL (e.g., https://docs.google.com/spreadsheets/d/.../edit#gid=0)
        """
        if not self.sheets_client:
            raise ValueError("Google Sheets client not initialized. Set GOOGLE_CREDENTIALS_JSON environment variable.")
        
        spreadsheet_id, gid = self._parse_sheets_url(url)
        spreadsheet = self.sheets_client.open_by_key(spreadsheet_id)
        
        if gid is not None:
            worksheet = spreadsheet.get_worksheet_by_id(gid)
        else:
            worksheet = spreadsheet.sheet1
        
        # Clear existing data and write new data
        worksheet.clear()
        worksheet.update([df.columns.tolist()] + df.values.tolist())
    
    def fetch_from_api(self, url, config={}):
        """Fetch data from API endpoint
        
        Args:
            url: API URL (supports {placeholder} syntax)
            config: Dict with API key, placeholders, etc.
        
        Returns:
            pandas DataFrame
        """
        # Replace placeholders in URL
        final_url = url
        for key, value in config.items():
            if key != 'api_key':  # Don't replace api_key in URL
                placeholder = f"{{{key}}}"
                if placeholder in final_url:
                    final_url = final_url.replace(placeholder, str(value))
        
        # Make API request
        headers = {}
        if 'api_key' in config:
            # Try common API key patterns
            if 'bearer' in str(config.get('auth_type', '')).lower():
                headers['Authorization'] = f"Bearer {config['api_key']}"
            elif 'token' in str(config.get('auth_type', '')).lower():
                headers['Authorization'] = f"Token {config['api_key']}"
            else:
                # Default: try as query parameter or header
                headers['X-API-Key'] = config['api_key']
        
        response = requests.get(final_url, headers=headers)
        response.raise_for_status()
        
        # Try to parse as JSON
        data = response.json()
        
        # Convert to DataFrame
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            # Try common keys
            if 'data' in data:
                df = pd.DataFrame(data['data'])
            elif 'results' in data:
                df = pd.DataFrame(data['results'])
            else:
                # Single record
                df = pd.DataFrame([data])
        else:
            raise ValueError(f"Unexpected API response format: {type(data)}")
        
        return df

