import os
import re
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from .channel_actions import ChannelAction
from .channel_data import (
    CHANNEL_HEADERS,
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
    
    def _clear_all_values(self) -> None:
        """Clear all values in the sheet except the header row."""
        self.sheet.values().clear(
            spreadsheetId=self.sheet_id,
            range=f"'{self.tab_name}'!A2:Z",
            body={}
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
    
    def _update_cell(self, row: int, col: int, value: str) -> None:
        """Update a specific cell in the sheet.
        
        Args:
            row: 1-indexed row number
            col: 1-indexed column number
            value: New value for the cell
        """
        # Convert to A1 notation
        col_letter = chr(ord('A') + col - 1)
        cell_range = f"'{self.tab_name}'!{col_letter}{row}"
        
        self.sheet.values().update(
            spreadsheetId=self.sheet_id,
            range=cell_range,
            valueInputOption='RAW',
            body={'values': [[value]]}
        ).execute()
    
    def _update_specific_cells(self, updates: List[Tuple[int, int, str]]) -> None:
        """Update multiple specific cells in the sheet.
        
        Args:
            updates: List of (row, col, value) tuples where row and col are 1-indexed
        """
        # Group updates by row for efficiency
        row_updates = {}
        for row, col, value in updates:
            if row not in row_updates:
                row_updates[row] = []
            row_updates[row].append((col, value))
        
        # Process updates row by row
        for row, col_values in row_updates.items():
            # Sort by column
            col_values.sort(key=lambda x: x[0])
            
            # Find continuous ranges to update
            ranges = []
            current_range = []
            last_col = None
            
            for col, value in col_values:
                if last_col is None or col == last_col + 1:
                    current_range.append(value)
                else:
                    if current_range:
                        ranges.append((last_col - len(current_range) + 1, current_range))
                        current_range = [value]
                last_col = col
            
            if current_range:
                ranges.append((last_col - len(current_range) + 1, current_range))
            
            # Update each range
            for start_col, values in ranges:
                # Convert to A1 notation
                start_col_letter = chr(ord('A') + start_col - 1)
                end_col_letter = chr(ord('A') + start_col + len(values) - 2)
                
                if len(values) == 1:
                    cell_range = f"'{self.tab_name}'!{start_col_letter}{row}"
                else:
                    cell_range = f"'{self.tab_name}'!{start_col_letter}{row}:{end_col_letter}{row}"
                
                self.sheet.values().update(
                    spreadsheetId=self.sheet_id,
                    range=cell_range,
                    valueInputOption='RAW',
                    body={'values': [values]}
                ).execute()

    def write_channels(self, channels: List[Dict], clear_actions: bool = False) -> None:
        """Write channels to the sheet with minimal changes for better version history.
        
        Args:
            channels: List of channels to write
            clear_actions: Whether to clear any actions (set to keep)
        """
        headers = list(CHANNEL_HEADERS)
        
        # Get existing data to compare
        existing_values = self._get_all_values()
        existing_headers = existing_values[0] if existing_values else []
        
        # If headers don't match or sheet is empty, we need to rewrite everything
        if not existing_values or existing_headers != headers:
            values = [headers]
            for channel in channels:
                if clear_actions and channel.get("action") not in [ChannelAction.KEEP.value, ChannelAction.NEW.value]:
                    channel["action"] = ChannelAction.KEEP.value
                    channel["target_value"] = ""
                values.append([channel.get(h, '') for h in headers])
            
            # Clear and rewrite
            self._clear_all_values()
            self._update_values(values)
            return
        
        # Create a map of existing channels by ID for quick lookup
        existing_channels = {}
        header_to_col = {header: idx for idx, header in enumerate(existing_headers)}
        
        # Find the column index for channel_id
        channel_id_col = header_to_col.get("channel_id")
        if channel_id_col is None:
            # If we can't find channel_id column, rewrite everything
            self.write_channels_full_rewrite(channels, clear_actions)
            return
        
        # Map existing channels by ID
        for row_idx, row in enumerate(existing_values[1:], start=2):  # Start from row 2 (1-indexed)
            if len(row) > channel_id_col:
                channel_id = row[channel_id_col]
                if channel_id:
                    existing_channels[channel_id] = (row_idx, row)
        
        # Prepare updates
        updates = []
        new_rows = []
        
        # Process each channel
        for channel in channels:
            channel_id = channel.get("channel_id", "")
            
            # Apply clear_actions if needed
            if clear_actions and channel.get("action") not in [ChannelAction.KEEP.value, ChannelAction.NEW.value]:
                channel["action"] = ChannelAction.KEEP.value
                channel["target_value"] = ""
            
            if channel_id in existing_channels:
                # Update existing channel
                row_idx, existing_row = existing_channels[channel_id]
                
                # Extend existing row if needed
                existing_row = existing_row + [''] * (len(headers) - len(existing_row))
                
                # Check which cells need updates
                for col_idx, header in enumerate(headers, start=1):  # 1-indexed columns
                    new_value = channel.get(header, '')
                    existing_value = existing_row[col_idx-1] if col_idx <= len(existing_row) else ''
                    
                    if new_value != existing_value:
                        updates.append((row_idx, col_idx, new_value))
                
                # Mark as processed
                del existing_channels[channel_id]
            else:
                # New channel to add
                new_rows.append([channel.get(h, '') for h in headers])
        
        # Apply all cell updates
        if updates:
            self._update_specific_cells(updates)
        
        # Add new rows if any
        if new_rows:
            # Find the next empty row
            next_row = len(existing_values) + 1
            
            # Append new rows
            self.sheet.values().append(
                spreadsheetId=self.sheet_id,
                range=f"'{self.tab_name}'!A{next_row}",
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body={'values': new_rows}
            ).execute()
        
        # Delete rows for channels that no longer exist
        if existing_channels:
            # We need to delete rows from bottom to top to avoid shifting issues
            rows_to_delete = sorted([row_idx for row_idx, _ in existing_channels.values()], reverse=True)
            
            # Delete each row
            for row_idx in rows_to_delete:
                # Create a delete request
                request = {
                    'deleteDimension': {
                        'range': {
                            'sheetId': int(self.tab_id),
                            'dimension': 'ROWS',
                            'startIndex': row_idx - 1,  # 0-indexed
                            'endIndex': row_idx  # exclusive end
                        }
                    }
                }
                
                # Execute the request
                self.sheet.batchUpdate(
                    spreadsheetId=self.sheet_id,
                    body={'requests': [request]}
                ).execute()
    
    def write_channels_full_rewrite(self, channels: List[Dict], clear_actions: bool = False) -> None:
        """Legacy method to completely rewrite the sheet.
        
        Args:
            channels: List of channels to write
            clear_actions: Whether to clear any actions (set to keep)
        """
        headers = list(CHANNEL_HEADERS)
        values = [headers]
        
        for channel in channels:
            if clear_actions and channel.get("action") not in [ChannelAction.KEEP.value, ChannelAction.NEW.value]:
                channel["action"] = ChannelAction.KEEP.value
                channel["target_value"] = ""
            values.append([channel.get(h, '') for h in headers])
        
        # First clear all values (except header)
        self._clear_all_values()
        # Then write new values
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
                existing_channels.append(create_channel_dict(channel, is_new=True))
        
        # Write back with cleared actions
        self.write_channels(existing_channels, clear_actions=True) 