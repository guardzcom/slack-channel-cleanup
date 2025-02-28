import csv
from typing import List, Dict
from datetime import datetime
from .channel_actions import ChannelAction

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

def export_channels_to_csv(channels: List[Dict], filename: str = None) -> str:
    """
    Export channels to a CSV file.
    
    Args:
        channels: List of channel dictionaries from Slack API
        filename: Optional filename, if not provided will generate one
        
    Returns:
        str: Path to the created CSV file
    """
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"slack_channels_{timestamp}.csv"
    
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        
        for channel in channels:
            # Convert timestamp to readable date
            created = datetime.fromtimestamp(float(channel["created"])).strftime("%Y-%m-%d")
            
            row = {
                "channel_id": channel["id"],
                "name": channel["name"],
                "is_private": channel["is_private"],
                "member_count": channel["num_members"],
                "created_date": created,
                "action": ChannelAction.KEEP.value,  # Default action
                "target_value": "",  # Empty for merge/rename target
                "notes": ""  # For any additional notes/comments
            }
            writer.writerow(row)
    
    return filename

def read_channels_from_csv(filename: str) -> List[Dict]:
    """
    Read channel actions from a CSV file.
    
    Args:
        filename: Path to the CSV file
        
    Returns:
        List of dictionaries containing channel information and actions
    """
    channels = []
    
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        # Validate headers
        missing_headers = set(CSV_HEADERS) - set(reader.fieldnames)
        if missing_headers:
            raise ValueError(f"CSV file is missing required headers: {', '.join(missing_headers)}")
        
        for row in reader:
            # Validate action
            action = row["action"].lower()
            if action not in ChannelAction.values():
                raise ValueError(
                    f"Invalid action '{action}' for channel {row['name']}. "
                    f"Must be one of: {', '.join(ChannelAction.values())}"
                )
            
            # Validate target value for merge and rename actions
            if action in [ChannelAction.MERGE.value, ChannelAction.RENAME.value] and not row["target_value"]:
                raise ValueError(
                    f"Target value is required for {action} action on channel {row['name']}"
                )
            
            channels.append(row)
    
    return channels 