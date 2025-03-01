import csv
from typing import List, Dict
from datetime import datetime
from .channel_actions import ChannelAction
import os

# Standard data structure for channel information
REQUIRED_HEADERS = [
    "channel_id",
    "name",
    "action",
    "target_value"
]

# All supported headers
CHANNEL_HEADERS = [
    "channel_id",
    "name",
    "description",
    "is_private",
    "is_shared",
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

def create_channel_dict(channel: Dict, is_new: bool = True) -> Dict:
    """
    Create a standardized channel dictionary from Slack API channel data.
    Converts raw Slack API data into our standard data structure.
    
    Args:
        channel: Raw channel data from Slack API
        is_new: Whether this is a newly discovered channel
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
            
    # Start with required fields
    result = {
        "channel_id": channel["id"],
        "name": channel["name"],
        "description": channel.get("purpose", {}).get("value", ""),
        "action": ChannelAction.NEW.value if is_new else ChannelAction.KEEP.value,
        "target_value": ""
    }
    
    # Add optional fields if available
    if "is_private" in channel:
        result["is_private"] = str(channel["is_private"]).lower()
    if "is_shared" in channel:
        result["is_shared"] = str(channel.get("is_shared", False)).lower()
    if "num_members" in channel:
        result["member_count"] = str(channel["num_members"])
    if "created" in channel:
        result["created_date"] = datetime.fromtimestamp(float(channel["created"])).strftime("%Y-%m-%d")
    if "last_activity" in CHANNEL_HEADERS:  # Only add if supported
        result["last_activity"] = last_activity
    if "notes" in CHANNEL_HEADERS:
        result["notes"] = ""
        
    return result

def write_channel_to_csv(writer: csv.DictWriter, channel: Dict):
    """Write a single channel to CSV file."""
    row = create_channel_dict(channel, is_new=False)
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
    
    # Prevent archiving shared channels
    if action == ChannelAction.ARCHIVE.value and channel.get('is_shared', '').lower() == 'true':
        raise ValueError(
            f"Cannot archive shared channel {channel.get('name')}. "
            "Slack Connect channels must be disconnected by workspace admins first."
        )
    
    # Validate target value is empty for keep and new actions
    if action in [ChannelAction.KEEP.value, ChannelAction.NEW.value] and channel.get('target_value'):
        raise ValueError(
            f"Target value must be empty for '{action}' action on channel {channel.get('name')}"
        )
    
    # Validate target value for rename action
    if action == ChannelAction.RENAME.value and not channel.get('target_value'):
        raise ValueError(
            f"Target value is required for {action} action on channel {channel.get('name')}"
        )

def validate_headers(headers: List[str]) -> None:
    """Validate that all required headers are present in the data structure."""
    missing = set(REQUIRED_HEADERS) - set(headers)
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