import os
import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from .channel_actions import ChannelAction
from .channel_csv import (
    CSV_HEADERS,
    create_channel_dict,
    validate_channel,
    validate_headers
)

# If modifying these scopes, delete the token.json file.
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_sheet_id_from_url(url: str) -> Tuple[str, str]:
    """Extract sheet ID and tab ID from Google Sheets URL."""
    # Extract spreadsheet ID
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        raise ValueError(
            "Invalid Google Sheets URL format.\n"
            "Expected: https://docs.google.com/spreadsheets/d/YOUR-SHEET-ID\n"
            "Please share your sheet with the service account email in service-account.json"
        )
    spreadsheet_id = match.group(1)
    
    # Extract tab/sheet ID (gid)
    gid_match = re.search(r"[#&]gid=(\d+)", url)
    sheet_id = gid_match.group(1) if gid_match else "0"  # Default to first sheet if not specified
    
    return spreadsheet_id, sheet_id

def get_credentials() -> Credentials:
    """Get Google service account credentials."""
    creds_file = 'service-account.json'
    
    if not os.path.exists(creds_file):
        raise ValueError(
            f"{creds_file} not found. Please follow the Google Sheets setup instructions in the README:\n"
            "1. Create a Google Cloud Project\n"
            "2. Create a service account and download the JSON key\n"
            "3. Save the key as service-account.json in this directory\n"
            "4. Share your sheet with the service account email"
        )
    
    try:
        creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        return creds
    except Exception as e:
        raise ValueError(
            f"Failed to load service account credentials: {str(e)}\n"
            "Please ensure you've followed all setup steps in the README."
        )

class SheetManager:
    """Manager for Google Sheets operations."""
    
    def __init__(self, sheet_url: str):
        """Initialize the sheet manager."""
        self.sheet_id, self.tab_id = get_sheet_id_from_url(sheet_url)
        try:
            self.service = build('sheets', 'v4', credentials=get_credentials())
            self.sheet = self.service.spreadsheets()
            
            # Get the sheet name from gid
            sheet_metadata = self.sheet.get(spreadsheetId=self.sheet_id).execute()
            sheets = sheet_metadata.get('sheets', [])
            sheet_properties = next(
                (sheet['properties'] for sheet in sheets if str(sheet['properties'].get('sheetId')) == self.tab_id),
                None
            )
            
            if not sheet_properties:
                raise ValueError(f"Sheet with gid={self.tab_id} not found in the spreadsheet")
                
            self.tab_name = sheet_properties['title']
            print(f"Using sheet: {self.tab_name}")
            
            # Verify we can access the sheet
            self._get_headers()
        except HttpError as e:
            if e.resp.status == 404:
                raise ValueError(f"Sheet not found. Please check the URL: {sheet_url}")
            elif e.resp.status == 403:
                raise ValueError("Permission denied. Please ensure you have access to the sheet.")
            raise
    
    def _get_headers(self) -> List[str]:
        """Get the headers from the first row."""
        result = self.sheet.values().get(
            spreadsheetId=self.sheet_id,
            range=f"'{self.tab_name}'!A1:Z1"
        ).execute()
        values = result.get('values', [])
        if not values:
            return []
        return values[0]
    
    def _get_all_values(self) -> List[List[str]]:
        """Get all values from the sheet."""
        result = self.sheet.values().get(
            spreadsheetId=self.sheet_id,
            range=f"'{self.tab_name}'!A:Z"
        ).execute()
        return result.get('values', [])
    
    def _update_values(self, values: List[List[str]]) -> None:
        """Update all values in the sheet."""
        self.sheet.values().update(
            spreadsheetId=self.sheet_id,
            range=f"'{self.tab_name}'!A1",
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
    
    def read_channels(self) -> List[Dict]:
        """Read channels from the sheet."""
        values = self._get_all_values()
        if not values:
            return []
        
        headers = values[0]
        validate_headers(headers)
        
        channels = []
        for row in values[1:]:
            # Pad row with empty strings if needed
            row_data = row + [''] * (len(headers) - len(row))
            channel = dict(zip(headers, row_data))
            validate_channel(channel)
            channels.append(channel)
        
        return channels
    
    def write_channels(self, channels: List[Dict], clear_actions: bool = False) -> None:
        """Write channels to the sheet.
        
        Args:
            channels: List of channels to write
            clear_actions: Whether to clear any actions (set to keep)
        """
        headers = list(CSV_HEADERS)
        values = [headers]
        
        for channel in channels:
            if clear_actions and channel.get("action") != ChannelAction.KEEP.value:
                channel["action"] = ChannelAction.KEEP.value
                channel["target_value"] = ""
            values.append([channel.get(h, '') for h in headers])
        
        self._update_values(values)
    
    def update_from_active_channels(self, active_channels: List[Dict]) -> None:
        """Update sheet with current channels and clear completed actions."""
        # Get existing channels
        existing_channels = self.read_channels()
        
        # Create lookup of active channel IDs
        existing_channel_ids = {ch.get("channel_id") for ch in existing_channels}
        
        # Add new channels
        for channel in active_channels:
            if channel["id"] not in existing_channel_ids:
                existing_channels.append(create_channel_dict(channel))
        
        # Write back with cleared actions
        self.write_channels(existing_channels, clear_actions=True) 