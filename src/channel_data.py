import csv
from typing import List, Dict
from datetime import datetime
from .channel_actions import ChannelAction
import os

# Standard data structure for channel information
CHANNEL_HEADERS = [
    "channel_id",
    "name",
    "is_private",
    "member_count",
    "created_date",
    "last_activity",
    "action",
    "target_value",
    "notes"
]

def get_default_filename() -> str:
    """Generate default filename with timestamp for CSV export."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"slack_channels_{timestamp}.csv"

def create_csv_writer(filename: str = None):
    """
    Create and initialize a CSV writer for channel data.
    
    Args:
        filename: Optional filename, if not provided will generate one
        
    Returns:
        Tuple[TextIO, csv.DictWriter, str]: File object, CSV writer, and filename
        
    Raises:
        IOError: If file cannot be created or written to
    """
    if not filename:
        filename = get_default_filename()
    
    try:
        f = open(filename, 'w', newline='', encoding='utf-8')
        writer = csv.DictWriter(f, fieldnames=CHANNEL_HEADERS)
        writer.writeheader()
        return f, writer, filename
    except IOError as e:
        raise IOError(f"Failed to create CSV file {filename}: {str(e)}")

def create_channel_dict(channel: Dict) -> Dict:
    """
    Create a standardized channel dictionary from Slack channel data.
    Converts raw Slack API data into our standard data structure.
    """
    # Get last activity from latest message timestamp if available
    last_activity = ""
    if channel.get("latest"):
        try:
            last_message = datetime.fromtimestamp(float(channel["latest"].get("ts", 0)))
            if last_message.year > 1970:  # Skip Unix epoch dates
                last_activity = last_message.strftime("%Y-%m-%d")
        except (ValueError, TypeError, AttributeError):
            pass  # Invalid timestamp or no latest message, leave empty
            
    return {
        "channel_id": channel["id"],
        "name": channel["name"],
        "is_private": str(channel["is_private"]).lower(),
        "member_count": str(channel["num_members"]),
        "created_date": datetime.fromtimestamp(float(channel["created"])).strftime("%Y-%m-%d"),
        "last_activity": last_activity,
        "action": ChannelAction.KEEP.value,
        "target_value": "",
        "notes": ""
    }

def write_channel_to_csv(writer: csv.DictWriter, channel: Dict):
    """Write a single channel to CSV file."""
    row = create_channel_dict(channel)
    writer.writerow(row)

def validate_channel(channel: Dict, validate_headers: bool = False) -> None:
    """
    Validate channel data, raising ValueError if invalid.
    
    Args:
        channel: Channel dictionary to validate
        validate_headers: Whether to validate required headers exist
    """
    if validate_headers:
        missing_headers = set(CHANNEL_HEADERS) - set(channel.keys())
        if missing_headers:
            raise ValueError(f"Missing required headers: {', '.join(missing_headers)}")
    
    # Validate action
    action = channel.get('action', '').lower() or ChannelAction.KEEP.value
    if action not in ChannelAction.values():
        raise ValueError(
            f"Invalid action '{action}' for channel {channel.get('name')}. "
            f"Must be one of: {', '.join(ChannelAction.values())}"
        )
    
    # Validate target value is empty for keep action
    if action == ChannelAction.KEEP.value and channel.get('target_value'):
        raise ValueError(
            f"Target value must be empty for 'keep' action on channel {channel.get('name')}"
        )
    
    # Validate target value for rename action
    if action == ChannelAction.RENAME.value and not channel.get('target_value'):
        raise ValueError(
            f"Target value is required for {action} action on channel {channel.get('name')}"
        )

def validate_headers(headers: List[str]) -> None:
    """Validate that all required headers are present in the data structure."""
    missing = set(CHANNEL_HEADERS) - set(headers)
    if missing:
        raise ValueError(f"Missing required headers: {', '.join(missing)}")

def read_channels_from_csv(filename: str) -> List[Dict]:
    """
    Read channel data from a CSV file.
    
    Args:
        filename: Path to the CSV file
        
    Returns:
        List[Dict]: List of channel dictionaries
        
    Raises:
        IOError: If file cannot be read
        ValueError: If CSV format is invalid
    """
    if not os.path.exists(filename):
        raise IOError(f"CSV file not found: {filename}")
        
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            validate_headers(reader.fieldnames)
            
            channels = []
            for row in reader:
                validate_channel(row)
                channels.append(row)
            
            return channels
    except IOError as e:
        raise IOError(f"Failed to read CSV file {filename}: {str(e)}")
    except csv.Error as e:
        raise ValueError(f"Invalid CSV format in {filename}: {str(e)}") 