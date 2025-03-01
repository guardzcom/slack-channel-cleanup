import csv
from typing import List, Dict
from datetime import datetime
from .channel_actions import ChannelAction
import os

CSV_HEADERS = [
    "channel_id",
    "name",
    "is_private",
    "member_count",
    "created_date",
    "action",
    "target_value",
    "notes"
]

def get_default_filename() -> str:
    """Generate default filename with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"slack_channels_{timestamp}.csv"

def create_csv_writer(filename: str = None):
    """
    Create and initialize a CSV writer.
    Returns the file object and writer.
    
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
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        return f, writer, filename
    except IOError as e:
        raise IOError(f"Failed to create CSV file {filename}: {str(e)}")

def write_channel_to_csv(writer: csv.DictWriter, channel: Dict):
    """
    Write a single channel to CSV.
    
    Args:
        writer: CSV writer
        channel: Channel data
    """
    # Convert timestamp to readable date
    created = datetime.fromtimestamp(float(channel["created"])).strftime("%Y-%m-%d")
    
    row = {
        "channel_id": channel["id"],
        "name": channel["name"],
        "is_private": str(channel["is_private"]).lower(),
        "member_count": str(channel["num_members"]),
        "created_date": created,
        "action": ChannelAction.KEEP.value,
        "target_value": "",  # Empty for rename target or archive redirect
        "notes": ""  # For any additional notes/comments
    }
    writer.writerow(row)

def read_channels_from_csv(filename: str) -> List[Dict]:
    """
    Read channel actions from a CSV file.
    
    Args:
        filename: Path to the CSV file
        
    Returns:
        List of dictionaries containing channel information and actions
        
    Raises:
        ValueError: If CSV format is invalid
        IOError: If file cannot be read
    """
    if not os.path.exists(filename):
        raise IOError(f"CSV file not found: {filename}")
        
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            # Validate headers
            missing_headers = set(CSV_HEADERS) - set(reader.fieldnames)
            if missing_headers:
                raise ValueError(f"CSV file is missing required headers: {', '.join(missing_headers)}")
            
            channels = []
            for row in reader:
                # Validate action
                action = row["action"].lower()
                if action not in ChannelAction.values():
                    raise ValueError(
                        f"Invalid action '{action}' for channel {row['name']}. "
                        f"Must be one of: {', '.join(ChannelAction.values())}"
                    )
                
                # Validate target value for rename action
                if action == ChannelAction.RENAME.value and not row["target_value"]:
                    raise ValueError(
                        f"Target value is required for {action} action on channel {row['name']}"
                    )
                
                channels.append(row)
            
            return channels
    except IOError as e:
        raise IOError(f"Failed to read CSV file {filename}: {str(e)}")
    except csv.Error as e:
        raise ValueError(f"Invalid CSV format in {filename}: {str(e)}") 